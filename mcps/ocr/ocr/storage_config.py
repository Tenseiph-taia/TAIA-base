"""
Centralized storage configuration for OCR service.

Ensures all paths are absolute, deterministic, and self-healing.
Uses lazy evaluation to support test isolation via OCR_DATA_DIR env var.
"""
import os
from pathlib import Path

# Determine project root dynamically
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_data_dir() -> Path:
    """Get data directory (supports OCR_DATA_DIR env var for testing)."""
    return Path(os.getenv("OCR_DATA_DIR", str(_PROJECT_ROOT / "data")))


def get_upload_dir() -> Path:
    """Get uploads directory."""
    return get_data_dir() / "uploads"


def get_tmp_dir() -> Path:
    """Get temp directory."""
    return get_data_dir() / "tmp"


def get_db_path() -> Path:
    """Get database path."""
    return get_data_dir() / "db" / "ocr.db"


# Legacy compatibility - evaluate lazily
UPLOAD_DIR = str(get_upload_dir())
TMP_DIR = str(get_tmp_dir())
DB_PATH = str(get_db_path())

# Cleanup policy (TTL for stored documents)
DOCUMENT_CLEANUP_HOURS = 24 * 15  # 15 days
DOCUMENT_CLEANUP_SECONDS = DOCUMENT_CLEANUP_HOURS * 3600


def ensure_storage_dirs():
    """
    Create all required directories.
    Idempotent: safe to call multiple times.
    """
    import logging
    _logger = logging.getLogger("taia-ocr")
    
    for path in [get_upload_dir(), get_tmp_dir()]:
        if not path.exists():
            _logger.info(f"[STORAGE] Creating directory: {path}")
        path.mkdir(parents=True, exist_ok=True)
    
    # Also ensure DB directory exists
    db_dir = get_db_path().parent
    if not db_dir.exists():
        _logger.info(f"[STORAGE] Creating DB directory: {db_dir}")
    db_dir.mkdir(parents=True, exist_ok=True)


def safe_write(path: str, data: bytes):
    """
    Write data to a file, ensuring parent directory exists.
    Prevents crashes if directory was deleted during runtime.
    """
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)