from __future__ import annotations

from enum import Enum
from typing import Optional, Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class OkNg(str, Enum):
    OK = "OK"
    NG = "NG"


class TestCase(BaseModel):
    row: int                    # Excel row number (1-based)
    test_no: int                # Value from Col A
    prerequisite: str
    test_detail: str            # The browser instruction
    expected_result: str
    data_no: str
    remarks: str
    num_cases: str
    test_date: str              # Empty if not yet run
    test_okng: str              # "OK", "NG", or ""
    screenshot_tab: str | None  # Tab name where screenshots go, None if no tab found


class WriteResultInput(BaseModel):
    row: int = Field(..., ge=2, le=65536, description="Excel row from get_test_cases")
    ok_ng: OkNg = Field(..., description="Exactly 'OK' or 'NG'")
    notes: str = Field(default="", max_length=1000, description="Written to Remarks col F if provided")

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Write OK/NG result to a specific test case row."
        }
    )


class EmbedScreenshotInput(BaseModel):
    test_no: int = Field(..., ge=1, description="The test number from Col A of the main sheet")
    image_b64: str = Field(..., max_length=10485760, description="Base64-encoded PNG or JPEG. Max 10MB.")
    caption: str = Field(default="", max_length=500, description="Step description shown above the screenshot")
    step_number: int = Field(default=1, ge=1, description="Step sequence within this test case")

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Embed a screenshot into the pre-existing screenshot tab for a test case."
        }
    )


class WorkbookMeta(BaseModel):
    workbook_id: str
    filename: str
    main_sheet_name: str
    test_count: int
    ok_count: int
    ng_count: int
    untested_count: int
    screenshot_tabs: list[str]   # All "No.X" tab names found


# Column positions (1-based)
class Col:
    NO          = 1   # A - test number (integer)
    PREREQ      = 2   # B
    TEST_DETAIL = 3   # C - browser instruction
    EXPECTED    = 4   # D
    DATA_NO     = 5   # E
    REMARKS     = 6   # F
    NUM_CASES   = 7   # G
    TEST_DATE   = 8   # H - TAIA writes
    TEST_OKNG   = 9   # I - TAIA writes: "OK" or "NG"
    TEST_TESTER = 10  # J - TAIA writes: "TAIA"
    # K, L, M - review columns, never touched

MAIN_SHEET_INDEX = 2   # Fallback index only; main sheet is detected dynamically
HEADER_ROW       = 1
DATA_START       = 2
TESTER_NAME      = "TAIA"


class ImportWorkbookInput(BaseModel):
    filename: str = Field(..., description="Original filename e.g. 'sprint_42.xlsx'. Used to derive workbook_id.")
    overwrite: bool = Field(default=False)

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Import a user's Excel test plan."
        }
    )


# ── New Models for General Excel Manipulation ─────────────────────────────────

class CellStyle(BaseModel):
    """Style options for a cell"""
    background_color: str | None = Field(None, description="Hex color for cell background (e.g., 'FF0000' for red)")
    font_color: str | None = Field(None, description="Hex color for font (e.g., '000000' for black)")
    bold: bool = Field(False, description="Make text bold")
    italic: bool = Field(False, description="Make text italic")
    underline: bool = Field(False, description="Underline text")
    font_size: int | None = Field(None, ge=8, le=72, description="Font size in points")
    border: Literal["none", "thin", "medium", "thick"] = Field("none", description="Border style")


class CellRef(BaseModel):
    """Reference to a cell using A1 notation or row/column"""
    sheet: str | int = Field(..., description="Sheet name or index (0-based)")
    row: int = Field(..., ge=1, le=1048576, description="1-based row number")
    column: int = Field(..., ge=1, le=16384, description="1-based column number")
    
    model_config = ConfigDict(
        json_schema_extra={
            "description": "Cell reference using row/column coordinates."
        }
    )


class CellValue(BaseModel):
    """A cell value with optional style"""
    row: int = Field(..., ge=1, description="1-based row number")
    column: int = Field(..., ge=1, description="1-based column number")
    value: Any = Field(default=None, description="Cell value (string, number, boolean, or formula)")
    is_formula: bool = Field(False, description="If True, value is treated as a formula starting with '='")
    style: CellStyle | None = Field(None, description="Optional cell styling")


class ReadSheetInput(BaseModel):
    """Input for reading a sheet"""
    workbook_id: str = Field(..., description="Workbook ID")
    sheet: str | int = Field(..., description="Sheet name or index (0-based)")
    start_row: int = Field(1, ge=1, description="First row to read (1-based, defaults to header row)")
    end_row: int | None = Field(None, ge=1, description="Last row to read (1-based, None reads to end)")
    start_col: int = Field(1, ge=1, description="First column to read (1-based)")
    end_col: int | None = Field(None, ge=1, description="Last column to read (1-based, None reads to end)")
    skip_empty_rows: bool = Field(True, description="Skip rows where all cells are empty")
    return_dicts: bool = Field(True, description="Return as list of dicts with column headers as keys")

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Read data from a sheet in the workbook."
        }
    )


class ReadSheetOutput(BaseModel):
    """Output from reading a sheet"""
    ok: bool
    workbook_id: str
    sheet_name: str
    sheet_index: int
    row_count: int
    col_count: int
    data: list[dict] | list[list] = Field(default_factory=list)
    headers: list[str] | None = Field(None, description="Column headers if return_dicts=True")


class WriteCellInput(BaseModel):
    """Input for writing to a single cell"""
    workbook_id: str = Field(..., description="Workbook ID")
    sheet: str | int = Field(..., description="Sheet name or index (0-based)")
    row: int = Field(..., ge=1, description="1-based row number")
    column: int = Field(..., ge=1, description="1-based column number")
    value: Any = Field(default=None, description="Cell value (string, number, boolean, or formula)")
    is_formula: bool = Field(False, description="If True, value is treated as a formula")
    style: CellStyle | None = Field(None, description="Optional cell styling")

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Write a value to a specific cell."
        }
    )


class WriteRangeInput(BaseModel):
    """Input for writing to a range of cells"""
    workbook_id: str = Field(..., description="Workbook ID")
    sheet: str | int = Field(..., description="Sheet name or index (0-based)")
    start_row: int = Field(1, ge=1, description="Starting row number (1-based)")
    start_col: int = Field(1, ge=1, description="Starting column number (1-based)")
    data: list[list] = Field(..., description="2D array of values to write")
    has_header: bool = Field(False, description="First row is a header (applies header styling)")
    style: CellStyle | None = Field(None, description="Style for data rows (header uses different styling)")

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Write a 2D array of values to a range of cells."
        }
    )


class SheetInfo(BaseModel):
    """Information about a sheet"""
    name: str
    index: int
    rows: int
    columns: int
    is_main_sheet: bool = False


class SheetListOutput(BaseModel):
    """Output for listing sheets"""
    ok: bool
    workbook_id: str
    sheet_count: int
    sheets: list[SheetInfo]
    main_sheet_name: str | None = Field(None, description="Name of main sheet if identified")


class CreateSheetInput(BaseModel):
    """Input for creating a new sheet"""
    workbook_id: str = Field(..., description="Workbook ID")
    name: str = Field(..., description="Sheet name")
    position: int | None = Field(None, ge=0, description="Position to insert sheet (0-based, None appends)")

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Create a new sheet in the workbook."
        }
    )


class DeleteSheetInput(BaseModel):
    """Input for deleting a sheet"""
    workbook_id: str = Field(..., description="Workbook ID")
    sheet: str | int = Field(..., description="Sheet name or index to delete")

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Delete a sheet from the workbook."
        }
    )


class GetWorkbookSummaryOutput(BaseModel):
    """Extended workbook summary"""
    ok: bool
    workbook_id: str
    filename: str
    sheet_count: int
    main_sheet_name: str | None
    test_count: int = 0
    ok_count: int = 0
    ng_count: int = 0
    untested_count: int = 0
    screenshot_tabs: list[str] = []
    created_at: str
    modified_at: str