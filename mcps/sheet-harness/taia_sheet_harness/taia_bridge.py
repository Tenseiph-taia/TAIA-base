"""
TAIA Bridge Module

Simple Python interface for TAIA backend to interact with the sheet harness.
Provides synchronous wrapper functions around the workbook operations.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any

from .workbook import (
    import_workbook, read_test_cases, write_result,
    embed_screenshot, get_workbook_meta,
)
from .models import OkNg, TestCase, WorkbookMeta

log = logging.getLogger(__name__)

# Import configuration from server module
from .server import WORKBOOKS_DIR, _resolve, _lock_path, _require_exists
import filelock

def taia_import_workbook(filename: str, file_bytes: bytes) -> Dict[str, Any]:
    """
    Import a workbook for TAIA.

    Args:
        filename: Original filename (used to derive workbook_id)
        file_bytes: Raw Excel file bytes

    Returns:
        Dict with import result and metadata
    """
    try:
        # Derive workbook_id from filename (strip extension, sanitize)
        workbook_id = Path(filename).stem
        workbook_id = ''.join(c for c in workbook_id if c.isalnum() or c in '-_')
        workbook_id = workbook_id[:128]  # Limit length

        path = _resolve(workbook_id)

        with filelock.FileLock(str(_lock_path(path)), timeout=10):
            meta = import_workbook(path, file_bytes)

        return {
            "success": True,
            "workbook_id": meta.workbook_id,
            "filename": meta.filename,
            "main_sheet_name": meta.main_sheet_name,
            "test_count": meta.test_count,
            "ok_count": meta.ok_count,
            "ng_count": meta.ng_count,
            "untested_count": meta.untested_count,
            "screenshot_tabs": meta.screenshot_tabs,
        }
    except Exception as e:
        log.error(f"Failed to import workbook: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": "import_failed",
        }


def taia_get_test_cases(workbook_id: str, untested_only: bool = False) -> Dict[str, Any]:
    """
    Get test cases from a workbook.

    Args:
        workbook_id: ID of the workbook
        untested_only: If True, return only untested cases

    Returns:
        Dict with test cases
    """
    try:
        path = _resolve(workbook_id)
        _require_exists(path)

        with filelock.FileLock(str(_lock_path(path)), timeout=10):
            cases = read_test_cases(path)

        if untested_only:
            cases = [c for c in cases if not c.test_okng]

        return {
            "success": True,
            "workbook_id": workbook_id,
            "count": len(cases),
            "test_cases": [c.model_dump() for c in cases],
        }
    except Exception as e:
        log.error(f"Failed to get test cases: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": "read_failed",
        }


def taia_write_result(workbook_id: str, row: int, ok_ng: str, notes: str = "") -> Dict[str, Any]:
    """
    Write test result to a workbook.

    Args:
        workbook_id: ID of the workbook
        row: Row number to update
        ok_ng: "OK" or "NG"
        notes: Optional notes to append to remarks

    Returns:
        Dict with result status
    """
    try:
        # Validate row
        if row < 2:
            return {
                "success": False,
                "error": "Row must be >= 2",
                "error_type": "validation",
            }

        # Parse OK/NG
        try:
            ok_ng_enum = OkNg(ok_ng.upper())
        except ValueError:
            return {
                "success": False,
                "error": "ok_ng must be 'OK' or 'NG'",
                "error_type": "validation",
            }

        path = _resolve(workbook_id)
        _require_exists(path)

        with filelock.FileLock(str(_lock_path(path)), timeout=10):
            write_result(path, row, ok_ng_enum, notes)

        return {
            "success": True,
            "workbook_id": workbook_id,
            "row": row,
            "ok_ng": ok_ng.upper(),
            "message": f"Row {row} updated with {ok_ng.upper()}",
        }
    except Exception as e:
        log.error(f"Failed to write result: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": "write_failed",
        }


def taia_embed_screenshot(workbook_id: str, test_no: int, image_b64: str, caption: str = "", step_number: int = 1) -> Dict[str, Any]:
    """
    Embed a screenshot in a workbook.

    Args:
        workbook_id: ID of the workbook
        test_no: Test number to associate screenshot with
        image_b64: Base64-encoded PNG/JPEG image
        caption: Caption for the screenshot
        step_number: Step sequence number

    Returns:
        Dict with embedding result
    """
    try:
        path = _resolve(workbook_id)
        _require_exists(path)

        with filelock.FileLock(str(_lock_path(path)), timeout=10):
            tab_name = embed_screenshot(path, test_no, image_b64, caption, step_number)

        return {
            "success": True,
            "workbook_id": workbook_id,
            "test_no": test_no,
            "tab_name": tab_name,
            "message": f"Screenshot embedded in tab '{tab_name}'",
        }
    except Exception as e:
        log.error(f"Failed to embed screenshot: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": "embed_failed",
        }


def taia_get_workbook_meta(workbook_id: str) -> Dict[str, Any]:
    """
    Get workbook metadata.

    Args:
        workbook_id: ID of the workbook

    Returns:
        Dict with workbook metadata
    """
    try:
        path = _resolve(workbook_id)
        _require_exists(path)

        with filelock.FileLock(str(_lock_path(path)), timeout=10):
            meta = get_workbook_meta(path)

        return {
            "success": True,
            "workbook_id": meta.workbook_id,
            "filename": meta.filename,
            "main_sheet_name": meta.main_sheet_name,
            "test_count": meta.test_count,
            "ok_count": meta.ok_count,
            "ng_count": meta.ng_count,
            "untested_count": meta.untested_count,
            "screenshot_tabs": meta.screenshot_tabs,
        }
    except Exception as e:
        log.error(f"Failed to get workbook meta: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": "meta_failed",
        }