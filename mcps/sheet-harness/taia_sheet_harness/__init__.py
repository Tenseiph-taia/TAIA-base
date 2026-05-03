"""TAIA Sheet Harness MCP Server.

Excel-based test harness for TAIA Task Level Testing.
"""

__version__ = "1.0.0"

# Expose bridge functions for direct TAIA integration
from .taia_bridge import (
    taia_import_workbook,
    taia_get_test_cases,
    taia_write_result,
    taia_embed_screenshot,
    taia_get_workbook_meta,
)
