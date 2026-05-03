import logging
import os
import re
from pathlib import Path
from typing import Optional

import base64
from filelock import FileLock, Timeout
from fastmcp import FastMCP

from .models import (
    ImportWorkbookInput, WriteResultInput, EmbedScreenshotInput,
    WorkbookMeta, OkNg, TestCase,
)
from .workbook import (
    import_workbook, read_test_cases, write_result,
    embed_screenshot, get_workbook_meta,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


# ── Exception hierarchy ───────────────────────────────────────────────────────

class SheetHarnessError(Exception):
    """Base for all known, user-facing errors."""

class ValidationError(SheetHarnessError):
    """Bad input from the caller — equivalent to HTTP 400."""

class StorageError(SheetHarnessError):
    """Disk / OS error — equivalent to HTTP 503."""


def _user_error(msg: str) -> dict:
    return {"ok": False, "error": msg, "error_type": "validation"}


def _lock_error() -> dict:
    return {"ok": False, "error": "Could not acquire file lock — another operation is in progress. Retry in a moment.", "error_type": "lock_timeout"}


def _storage_error(exc: Exception) -> dict:
    log.error("Storage error: %s", exc, exc_info=True)
    return {"ok": False, "error": "Storage error. Check server logs.", "error_type": "server"}


# ── Configuration ─────────────────────────────────────────────────────────────

WORKBOOKS_DIR = Path(os.getenv("WORKBOOKS_DIR", "/workbooks"))
LOCK_TIMEOUT  = int(os.getenv("LOCK_TIMEOUT_SECONDS", "10"))
MAX_WORKBOOKS = int(os.getenv("MAX_WORKBOOKS", "100"))
MAX_ROW       = 65_536

WORKBOOKS_DIR.mkdir(parents=True, exist_ok=True)

mcp = FastMCP(
    name="taia-sheet-harness",
    instructions=(
        "TAIA Excel test harness for LLM orchestration. "
        "Import user Excel files, read test cases, write OK/NG results, embed screenshots. "
        "The main test sheet is always at index 2 (third tab). "
        "Screenshot tabs are pre-created by the user (e.g. 'No.2', 'No.8-10'). "
        "Never create screenshot tabs — they must already exist. "
        "Never touch columns K, L, M (human review). "
        "Always call get_test_cases first to obtain valid row numbers."
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _resolve(workbook_id: str) -> Path:
    if not _SAFE_NAME.match(workbook_id):
        raise ValueError(f"Invalid workbook_id '{workbook_id}': use only letters, digits, _ and -")
    if len(workbook_id) > 128:
        raise ValueError("workbook_id exceeds 128 character limit.")
    resolved = (WORKBOOKS_DIR / f"{workbook_id}.xlsx").resolve()
    try:
        resolved.relative_to(WORKBOOKS_DIR.resolve())
    except ValueError:
        raise ValueError("workbook_id resolves outside the workbooks directory.")
    return resolved


def _lock_path(path: Path) -> Path:
    return path.with_suffix(".lock")


def _require_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Workbook '{path.stem}' not found. "
            f"Call import_workbook first or check list_workbooks."
        )


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Import a user's Excel test plan. Accepts base64-encoded .xlsx file. "
        "The file must have at least 3 sheets. The main test sheet is at index 2 (third tab). "
        "Screenshot tabs (e.g. 'No.2', 'No.8-10') should already exist — they are never created by automation. "
        "Returns workbook_id and test case count."
    )
)
def import_workbook_tool(
    file_b64: str,
    filename: str,
    overwrite: bool = False,
) -> dict:
    try:
        inp = ImportWorkbookInput(
            file_b64=file_b64,
            filename=filename,
            overwrite=overwrite,
        )
    except Exception as exc:
        return _user_error(f"Invalid input: {exc}")

    # Derive workbook_id from filename (strip extension, sanitize)
    workbook_id = Path(filename).stem
    if not _SAFE_NAME.match(workbook_id):
        # Fallback: use sanitized name
        workbook_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", workbook_id)
        workbook_id = workbook_id[:128]

    try:
        path = _resolve(workbook_id)
    except ValueError as exc:
        return _user_error(str(exc))

    if path.exists() and not inp.overwrite:
        return {
            "ok": False,
            "error": f"Workbook '{workbook_id}' already exists. Set overwrite=true to replace it.",
        }

    if len(list(WORKBOOKS_DIR.glob("*.xlsx"))) >= MAX_WORKBOOKS and not path.exists():
        return {"ok": False, "error": f"Maximum workbook limit ({MAX_WORKBOOKS}) reached."}

    try:
        # file_b64 is a base64-encoded string - decode it to bytes
        # Handle case where raw bytes were incorrectly decoded as latin1
        try:
            file_bytes = base64.b64decode(inp.file_b64)
        except Exception:
            # If it's not valid base64, it might be raw bytes that were decoded as latin1
            # Re-encode to latin1 to get original bytes
            file_bytes = inp.file_b64.encode('latin1')
        with FileLock(str(_lock_path(path)), timeout=LOCK_TIMEOUT):
            meta = import_workbook(path, file_bytes)
    except Timeout:
        return _lock_error()
    except ValueError as exc:
        return _user_error(str(exc))
    except OSError as exc:
        return _storage_error(exc)
    except Exception as exc:
        log.error("Unexpected error during import: %s", exc, exc_info=True)
        return {"ok": False, "error": f"Import failed: {exc}", "error_type": "server"}

    return {
        "ok": True,
        "workbook_id": meta.workbook_id,
        "filename": meta.filename,
        "main_sheet_name": meta.main_sheet_name,
        "test_count": meta.test_count,
        "ok_count": meta.ok_count,
        "ng_count": meta.ng_count,
        "untested_count": meta.untested_count,
        "screenshot_tabs": meta.screenshot_tabs,
        "message": f"Workbook imported with {meta.test_count} test cases.",
    }


@mcp.tool(
    description=(
        "Read all test cases from the imported workbook's main sheet (index 2). "
        "Each test case includes its row number — use this row number when writing results. "
        "Call this before any write operation. "
        "Rows without a numeric value in column A (test number) are skipped (section headers)."
    )
)
def get_test_cases(
    workbook_id: str,
    untested_only: bool = False,
) -> dict:
    try:
        path = _resolve(workbook_id)
        _require_exists(path)
    except (ValueError, FileNotFoundError) as exc:
        return _user_error(str(exc))

    try:
        with FileLock(str(_lock_path(path)), timeout=LOCK_TIMEOUT):
            cases = read_test_cases(path)
    except Timeout:
        return _lock_error()
    except OSError as exc:
        return _storage_error(exc)

    if untested_only:
        cases = [c for c in cases if not c.test_okng]

    return {
        "ok": True,
        "workbook_id": workbook_id,
        "count": len(cases),
        "test_cases": [c.model_dump() for c in cases],
    }


@mcp.tool(
    description=(
        "Write OK or NG result to a specific test case row. "
        "Also writes today's date and 'TAIA' as the tester. "
        "Row number must come from get_test_cases. "
        "OK/NG values are exactly 'OK' or 'NG' (case-sensitive)."
    )
)
def write_result_tool(
    workbook_id: str,
    row: int,
    ok_ng: OkNg,
    notes: str = "",
) -> dict:
    if err := _validate_row(row):
        return _user_error(err)

    try:
        path = _resolve(workbook_id)
    except ValueError as exc:
        return _user_error(str(exc))

    try:
        _require_exists(path)
    except FileNotFoundError as exc:
        return _user_error(str(exc))

    try:
        with FileLock(str(_lock_path(path)), timeout=LOCK_TIMEOUT):
            write_result(path, row, ok_ng, notes or "")
    except Timeout:
        return _lock_error()
    except ValueError as exc:
        return _user_error(str(exc))
    except OSError as exc:
        return _storage_error(exc)

    log.info("write_result workbook=%s row=%d ok_ng=%s", workbook_id, row, ok_ng.value)
    return {
        "ok": True,
        "workbook_id": workbook_id,
        "row": row,
        "ok_ng": ok_ng.value,
        "message": f"Row {row} updated with {ok_ng.value}.",
    }


def _validate_row(row: int) -> Optional[str]:
    if row < 2:
        return "Row must be >= 2 (row 1 is the header)."
    if row > MAX_ROW:
        return f"Row {row} exceeds the maximum of {MAX_ROW}."
    return None


@mcp.tool(
    description=(
        "Embed a screenshot into the pre-existing screenshot tab for a test case. "
        "Tab must already exist in the workbook (user-created). "
        "If no tab exists for the test number, returns an error — do not create new tabs. "
        "Multiple screenshots for the same test stack vertically. "
        "image_b64 must be base64-encoded PNG or JPEG. Maximum size: 10 MB base64."
    )
)
def embed_screenshot_tool(
    workbook_id: str,
    test_no: int,
    image_b64: str,
    caption: str = "",
    step_number: int = 1,
) -> dict:
    if err := _validate_row(test_no):
        return _user_error(err)

    try:
        path = _resolve(workbook_id)
    except ValueError as exc:
        return _user_error(str(exc))

    try:
        _require_exists(path)
    except FileNotFoundError as exc:
        return _user_error(str(exc))

    try:
        with FileLock(str(_lock_path(path)), timeout=LOCK_TIMEOUT):
            tab_name = embed_screenshot(path, test_no, image_b64, caption or "", step_number)
    except Timeout:
        return _lock_error()
    except ValueError as exc:
        return _user_error(str(exc))
    except OSError as exc:
        return _storage_error(exc)

    log.info("embed_screenshot workbook=%s test_no=%d tab=%s", workbook_id, test_no, tab_name)
    return {
        "ok": True,
        "workbook_id": workbook_id,
        "test_no": test_no,
        "tab_name": tab_name,
        "message": f"Screenshot embedded in tab '{tab_name}'.",
    }


@mcp.tool(
    description=(
        "Return OK/NG/untested counts and screenshot tab info for a workbook. "
        "Computed from the live main sheet data."
    )
)
def get_workbook_summary_tool(
    workbook_id: str,
) -> dict:
    try:
        path = _resolve(workbook_id)
        _require_exists(path)
    except (ValueError, FileNotFoundError) as exc:
        return _user_error(str(exc))

    try:
        with FileLock(str(_lock_path(path)), timeout=LOCK_TIMEOUT):
            meta = get_workbook_meta(path)
    except Timeout:
        return _lock_error()
    except OSError as exc:
        return _storage_error(exc)

    return {
        "ok": True,
        "workbook_id": meta.workbook_id,
        "filename": meta.filename,
        "main_sheet_name": meta.main_sheet_name,
        "test_count": meta.test_count,
        "ok_count": meta.ok_count,
        "ng_count": meta.ng_count,
        "untested_count": meta.untested_count,
        "screenshot_tabs": meta.screenshot_tabs,
    }


@mcp.tool(
    description="List all workbooks in the workbooks directory."
)
def list_workbooks_tool() -> dict:
    workbooks = []
    for p in sorted(WORKBOOKS_DIR.glob("*.xlsx")):
        stat = p.stat()
        workbooks.append({
            "workbook_id": p.stem,
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
        })
    return {"ok": True, "count": len(workbooks), "workbooks": workbooks}


@mcp.tool(
    description="Validate that a workbook has the correct structure and all required sheets."
)
def validate_workbook_tool(
    workbook_id: str,
) -> dict:
    try:
        path = _resolve(workbook_id)
        _require_exists(path)
    except (ValueError, FileNotFoundError) as exc:
        return _user_error(str(exc))

    try:
        with FileLock(str(_lock_path(path)), timeout=LOCK_TIMEOUT):
            from openpyxl import load_workbook as load_wb
            wb = load_wb(str(path), read_only=True)
            sheet_names = wb.sheetnames

            if len(sheet_names) < 3:
                return _user_error(f"Workbook has only {len(sheet_names)} sheet(s). Expected at least 3 (Cover, Revisions, main test sheet).")

            main_sheet_ws = _find_main_sheet(wb)
            main_sheet = main_sheet_ws.title

            # Header already validated by _find_main_sheet

            # Check for screenshot tabs
            screenshot_tabs = parse_tab_map(wb)

    except Timeout:
        return _lock_error()
    except OSError as exc:
        return _storage_error(exc)

    return {
        "ok": True,
        "workbook_id": workbook_id,
        "main_sheet": main_sheet,
        "screenshot_tabs": sorted(set(screenshot_tabs.values())),
        "message": "Workbook structure is valid.",
    }


# Import parse_tab_map from workbook for validation
from .workbook import parse_tab_map, _find_main_sheet, HEADER_ROW, Col


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    port = int(os.getenv("PORT_MCP", os.getenv("PORT", "8006")))
    mcp.run(transport="sse", host="0.0.0.0", port=port)