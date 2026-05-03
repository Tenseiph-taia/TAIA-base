from __future__ import annotations

from enum import Enum
from typing import Optional
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
    NO          = 1   # A — test number (integer)
    PREREQ      = 2   # B
    TEST_DETAIL = 3   # C — browser instruction
    EXPECTED    = 4   # D
    DATA_NO     = 5   # E
    REMARKS     = 6   # F
    NUM_CASES   = 7   # G
    TEST_DATE   = 8   # H — TAIA writes
    TEST_OKNG   = 9   # I — TAIA writes: "OK" or "NG"
    TEST_TESTER = 10  # J — TAIA writes: "TAIA"
    # K, L, M — review columns, never touched

MAIN_SHEET_INDEX = 2   # Always the third tab (0-based)
HEADER_ROW       = 1
DATA_START       = 2
TESTER_NAME      = "TAIA"


class ImportWorkbookInput(BaseModel):
    file_b64: str = Field(..., max_length=52428800, description="Base64-encoded .xlsx file content. Max 50MB.")
    filename: str = Field(..., description="Original filename e.g. 'sprint_42.xlsx'. Used to derive workbook_id.")
    overwrite: bool = Field(default=False)

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Import a user's Excel test plan."
        }
    )