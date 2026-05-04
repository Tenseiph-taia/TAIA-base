from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import os
import logging
from pathlib import Path

from .server import _resolve   # reuse the existing resolver

log = logging.getLogger(__name__)

download_app = FastAPI()

@download_app.get("/download/{workbook_id}")
async def download_workbook(workbook_id: str):
    try:
        path = _resolve(workbook_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workbook_id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Workbook not found")
    filename = f"{workbook_id}.xlsx"
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )