#!/usr/bin/env python3
"""
MCP OCR — Database & Storage Reset Script

WARNING: This permanently deletes all OCR documents, pages, and uploaded images.
The SQLite database and storage directories are recreated automatically on next startup.

Usage:
    uv run python reset_db.py
    # or
    python reset_db.py
"""
import os
import sys
import shutil
import subprocess
import time
from pathlib import Path


def stop_services():
    """Kill any running OCR service processes (safely skips this script)."""
    print("[1/3] Stopping OCR service processes...")
    current_pid = os.getpid()

    if sys.platform == "win32":
        # Use PowerShell to find & kill only processes whose command line
        # contains main_api.py or main_mcp.py, excluding our own PID.
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
            "| Where-Object { $_.CommandLine -match 'main_api|main_mcp' } "
            f"| Where-Object {{ $_.ProcessId -ne {current_pid} }} "
            "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass
    else:
        for proc_name in ["main_api.py", "main_mcp.py"]:
            try:
                subprocess.run(
                    ["pkill", "-f", f"python {proc_name}"],
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass

    time.sleep(1)
    print("      Done.")


def remove_storage(data_dir: Path):
    """Delete DB and uploaded documents."""
    print("[2/3] Removing database and uploaded documents...")

    db_file = data_dir / "db" / "ocr.db"
    uploads_dir = data_dir / "uploads"

    if db_file.exists():
        db_file.unlink()
        print(f"      Deleted {db_file}")

    # Also remove WAL files
    for ext in ("-wal", "-shm"):
        wal = Path(str(db_file) + ext)
        if wal.exists():
            wal.unlink()
            print(f"      Deleted {wal}")

    if uploads_dir.exists():
        for item in uploads_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        print(f"      Cleared {uploads_dir}")

    print("      Done.")


def ensure_dirs(data_dir: Path):
    """Recreate empty directories so startup is clean."""
    print("[3/3] Recreating storage directories...")
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (data_dir / "tmp").mkdir(parents=True, exist_ok=True)
    print("      Done.")


def main():
    script_dir = Path(__file__).resolve().parent
    data_dir = script_dir / "data"

    print("=== MCP OCR Database Reset ===\n")

    stop_services()
    remove_storage(data_dir)
    ensure_dirs(data_dir)

    print("\n=== Reset complete! ===")
    print("You can now restart the service with:")
    print("    uv run python main_api.py")
    print("    uv run python main_mcp.py")
    print("  or")
    print("    bash start.sh")


if __name__ == "__main__":
    main()
