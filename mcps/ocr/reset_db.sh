#!/bin/bash
# ---------------------------------------------------------------
# MCP OCR - Database & Storage Reset Script
# ---------------------------------------------------------------
# WARNING: This will permanently delete all OCR documents and data!
# The database and uploads will be recreated automatically on next startup.
# ---------------------------------------------------------------

set -e

cd "$(dirname "$0")

echo "=== MCP OCR Database Reset ==="
echo ""

# 1. Stop running OCR processes
echo "[1/3] Stopping OCR service processes..."
pkill -f "python main_api.py" 2>/dev/null || true
pkill -f "python main_mcp.py" 2>/dev/null || true
sleep 1
echo "      Done."

# 2. Remove database file and uploads
echo "[2/3] Removing database and uploaded documents..."
rm -f data/db/ocr.db
rm -rf data/uploads/*
echo "      Done."

# 3. Optional: remove WAL files if they exist
echo "[3/3] Cleaning up WAL/shm files..."
rm -f data/db/ocr.db-wal data/db/ocr.db-shm
echo "      Done."

echo ""
echo "=== Reset complete! ==="
echo "You can now restart the service with: bash start.sh"
