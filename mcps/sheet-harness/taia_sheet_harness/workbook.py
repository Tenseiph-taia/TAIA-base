from __future__ import annotations

import base64
import io
import logging
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill, Side
from openpyxl.styles.fills import PatternFill

from .models import (
    Col, DATA_START, HEADER_ROW,
    OkNg, TestCase, WorkbookMeta, WriteResultInput,
)

log = logging.getLogger(__name__)

# ── Limits ─────────────────────────────────────────────────────────────────────

MAX_TEXT_LEN = 32_767  # Excel single-cell character limit
MAX_IMAGE_B64_BYTES = 10_485_760  # 10 MB of base64 input

_BACKUP_RETAIN = 5  # Number of backups to keep per workbook

# ── Palette ────────────────────────────────────────────────────────────────────

_C = {
    "ok_bg": "C6EFCE",
    "ok_fg": "276221",
    "ng_bg": "FFC7CE",
    "ng_fg": "9C0006",
    "header_bg": "1F3864",
    "header_fg": "FFFFFF",
    "border": "BFBFBF",
}

_thin = Side(style="thin", color=_C["border"])
_border = Side(style="thin", color=_C["border"])
_center = Font(name="Arial", size=10)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", start_color=hex_color, fgColor=hex_color)


def _font(color: str = "000000", bold: bool = False, size: int = 10) -> Font:
    return Font(name="Arial", color=color, bold=bold, size=size)


def _backup(path: Path) -> None:
    """Create a timestamped backup of the workbook. Keeps last _BACKUP_RETAIN backups."""
    if not path.exists():
        return
    backup_dir = path.parent / ".backups"
    backup_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shutil.copy2(path, backup_dir / f"{path.stem}_{ts}.xlsx")
    existing = sorted(backup_dir.glob(f"{path.stem}_*.xlsx"))
    for old in existing[:-_BACKUP_RETAIN]:
        old.unlink(missing_ok=True)


def _atomic_save(wb, path: Path) -> None:
    """Write to a temp file then atomically rename — prevents corrupt workbooks on crash."""
    import shutil
    if path.exists():
        _backup(path)
    tmp = path.with_suffix(".xlsx.tmp")
    try:
        wb.close()
        wb.save(str(tmp))
        shutil.move(str(tmp), str(path))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── Tab name parsing ───────────────────────────────────────────────────────────

def parse_tab_map(wb) -> dict[int, str]:
    """
    Read all tab names from index 3 onwards.
    For "No.2" → {2: "No.2"}
    For "No.8-10" → {8: "No.8-10", 9: "No.8-10", 10: "No.8-10"}
    Return dict mapping test_no (int) to tab name (str).
    Handles both "No.2" and "No.8-10" formats.
    Ignores tabs that don't match the pattern.
    """
    result: dict[int, str] = {}
    sheet_names = wb.sheetnames
    for name in sheet_names[3:]:  # Skip indices 0,1,2 (Cover, Revisions, main)
        name_strip = name.strip()
        if name_strip.startswith("No."):
            range_part = name_strip[3:]  # After "No."
            if "-" in range_part:
                try:
                    start, end = map(int, range_part.split("-"))
                    for n in range(start, end + 1):
                        result[n] = name_strip
                except ValueError:
                    continue
            else:
                try:
                    n = int(range_part)
                    result[n] = name_strip
                except ValueError:
                    continue
    return result


# ── Import ─────────────────────────────────────────────────────────────────────

def import_workbook(path: Path, file_bytes: bytes) -> WorkbookMeta:
    """
    Write file_bytes to path atomically.
    Open with openpyxl, validate tab count >= 3.
    Parse tab map. Read main sheet. Return WorkbookMeta.
    """
    _atomic_save_bytes(path, file_bytes)
    return get_workbook_meta(path)


def _atomic_save_bytes(path: Path, file_bytes: bytes) -> None:
    """Write bytes to a temp file then atomically rename."""
    if path.exists():
        _backup(path)
    tmp = path.with_suffix(".xlsx.tmp")
    try:
        tmp.write_bytes(file_bytes)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── Sheet discovery ──────────────────────────────────────────────────────────────

def _find_main_sheet(wb) -> object:
    """
    Find the main test sheet by scanning for header value "#" in A1.
    Accepts "#", "No.", "No".
    Returns the worksheet object.
    Falls back to index 2 if no match found.
    Raises ValueError if no main sheet found.
    """
    # First pass: scan by header
    for ws in wb.worksheets:
        val = ws.cell(row=1, column=1).value
        if val is not None and str(val).strip() in ("#", "No.", "No"):
            return ws
    # Fallback: index 2 if it exists
    if len(wb.worksheets) > 2:
        log.warning("No header match found — falling back to sheet index 2: %s", wb.worksheets[2].title)
        return wb.worksheets[2]
    raise ValueError("Could not identify main test sheet. Workbook must have at least 3 sheets.")


# ── Reading ────────────────────────────────────────────────────────────────────

def read_test_cases(path: Path) -> list[TestCase]:
    """
    Open workbook (data_only=True).
    Get ws = _find_main_sheet(wb).
    Iterate from DATA_START to max_row.
    Skip any row where Col A is None or not castable to int — these are section header rows.
    Only rows with a numeric value in Col A are test cases.
    Resolve screenshot_tab from tab_map for each test_no.
    Return list[TestCase].
    """
    wb = load_workbook(str(path), data_only=True)
    if len(wb.worksheets) < 3:
        return []

    ws = _find_main_sheet(wb)
    tab_map = parse_tab_map(wb)
    cases: list[TestCase] = []

    for row_idx in range(DATA_START, ws.max_row + 1):
        cell_val = ws.cell(row=row_idx, column=Col.NO).value

        # Skip if Col A is empty or not an integer (section headers)
        if cell_val is None:
            continue
        try:
            test_no = int(cell_val)
        except (ValueError, TypeError):
            continue

        prerequisite = _strval(ws.cell(row=row_idx, column=Col.PREREQ).value)
        test_detail = _strval(ws.cell(row=row_idx, column=Col.TEST_DETAIL).value)
        expected_result = _strval(ws.cell(row=row_idx, column=Col.EXPECTED).value)
        data_no = _strval(ws.cell(row=row_idx, column=Col.DATA_NO).value)
        remarks = _strval(ws.cell(row=row_idx, column=Col.REMARKS).value)
        num_cases = _strval(ws.cell(row=row_idx, column=Col.NUM_CASES).value)

        test_date = _strval(ws.cell(row=row_idx, column=Col.TEST_DATE).value)
        test_okng = _strval(ws.cell(row=row_idx, column=Col.TEST_OKNG).value)

        screenshot_tab = tab_map.get(test_no)

        cases.append(
            TestCase(
                row=row_idx,
                test_no=test_no,
                prerequisite=prerequisite,
                test_detail=test_detail,
                expected_result=expected_result,
                data_no=data_no,
                remarks=remarks,
                num_cases=num_cases,
                test_date=test_date,
                test_okng=test_okng,
                screenshot_tab=screenshot_tab,
            )
        )

    return cases


def _strval(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


# ── Writing ────────────────────────────────────────────────────────────────────

def write_result(path: Path, row: int, ok_ng: OkNg, notes: str = "") -> None:
    """
    Load workbook (not data_only).
    Write to ws = _find_main_sheet(wb):
      - Col H (TEST_DATE): datetime.now().strftime("%Y-%m-%d")
      - Col I (TEST_OKNG): ok_ng.value — "OK" in green fill, "NG" in red fill
      - Col J (TEST_TESTER): "TAIA"
      - If notes provided: append to Col F (REMARKS)
    Atomic save.
    """
    wb = load_workbook(str(path))
    ws = _find_main_sheet(wb)

    today = datetime.now().strftime("%Y-%m-%d")
    ws.cell(row=row, column=Col.TEST_DATE, value=today)
    ws.cell(row=row, column=Col.TEST_OKNG, value=ok_ng.value)
    ws.cell(row=row, column=Col.TEST_TESTER, value="TAIA")

    # Styling for OK/NG
    if ok_ng == OkNg.OK:
        ws.cell(row=row, column=Col.TEST_OKNG).fill = _fill(_C["ok_bg"])
        ws.cell(row=row, column=Col.TEST_OKNG).font = _font(_C["ok_fg"], bold=True)
    else:
        ws.cell(row=row, column=Col.TEST_OKNG).fill = _fill(_C["ng_bg"])
        ws.cell(row=row, column=Col.TEST_OKNG).font = _font(_C["ng_fg"], bold=True)

    ws.cell(row=row, column=Col.TEST_DATE).font = _font(size=9)
    ws.cell(row=row, column=Col.TEST_TESTER).font = _font(bold=True, size=10)

    if notes:
        current = _strval(ws.cell(row=row, column=Col.REMARKS).value)
        new_val = f"{current}; {notes}" if current else notes
        ws.cell(row=row, column=Col.REMARKS, value=new_val[:MAX_TEXT_LEN])

    _atomic_save(wb, path)


# ── Screenshots ────────────────────────────────────────────────────────────────

def embed_screenshot(path: Path, test_no: int, image_b64: str, caption: str, step_number: int) -> str:
    """
    Load workbook.
    Get tab_name from tab_map for test_no — raise ValueError if not found.
    Get ws = wb[tab_name].
    Find next available row to place screenshot (scan down from row 3 for empty anchor point).
    Write caption text to that row, Col A.
    Embed openpyxl Image anchored at Col B of the next row.
    Scale image to max width 500px maintaining aspect ratio.
    Set row height to fit.
    Atomic save.
    Return tab_name as confirmation.
    """
    if len(image_b64) > MAX_IMAGE_B64_BYTES:
        raise ValueError(
            f"Image data too large ({len(image_b64):,} bytes base64). "
            f"Maximum is {MAX_IMAGE_B64_BYTES:,} bytes."
        )

    wb = load_workbook(str(path))
    tab_map = parse_tab_map(wb)

    if test_no not in tab_map:
        raise ValueError(f"No screenshot tab found for test No. {test_no}")

    tab_name = tab_map[test_no]
    ws = wb[tab_name]

    # Find next available row (start from row 3, find first completely empty row in cols A-C)
    next_row = 3
    while True:
        has_content = False
        for col in range(1, 4):
            if ws.cell(row=next_row, column=col).value is not None:
                has_content = True
                break
        if not has_content:
            break
        next_row += 1

    # Write caption
    ws.cell(row=next_row, column=1, value=caption or f"Step {step_number}")
    ws.cell(row=next_row, column=1).font = _font(bold=True, size=10)

    # Decode and embed image
    try:
        img_data = base64.b64decode(image_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image data: {exc}") from exc

    img_stream = io.BytesIO(img_data)
    xl_img = XLImage(img_stream)

    # Scale to max 500px width
    max_w = 500
    if xl_img.width and xl_img.width > max_w:
        scale = max_w / xl_img.width
        xl_img.width = int(xl_img.width * scale)
        xl_img.height = int((xl_img.height or 100) * scale)

    # Anchor at Col B, next row
    col_letter = "B"
    ws.add_image(xl_img, f"{col_letter}{next_row + 1}")

    # Set row height to fit image
    if xl_img.height:
        ws.row_dimensions[next_row + 1].height = xl_img.height * 0.75

    _atomic_save(wb, path)
    return tab_name


# ── Summary ────────────────────────────────────────────────────────────────────

def get_workbook_meta(path: Path) -> WorkbookMeta:
    """
    Read test cases, count OK/NG/untested.
    Return WorkbookMeta.
    """
    cases = read_test_cases(path)
    ok_count = sum(1 for c in cases if c.test_okng == "OK")
    ng_count = sum(1 for c in cases if c.test_okng == "NG")
    untested = sum(1 for c in cases if not c.test_okng)

    wb = load_workbook(str(path), read_only=True)
    main_sheet = _find_main_sheet(wb)
    main_sheet_name = main_sheet.title
    tab_map = parse_tab_map(wb)

    return WorkbookMeta(
        workbook_id=path.stem,
        filename=path.name,
        main_sheet_name=main_sheet_name,
        test_count=len(cases),
        ok_count=ok_count,
        ng_count=ng_count,
        untested_count=untested,
        screenshot_tabs=sorted(set(tab_map.values())),
    )