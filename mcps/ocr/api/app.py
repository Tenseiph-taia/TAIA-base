import re
import asyncio
import uuid
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from ocr.router import run_ocr, extract_pages, ocr_single_page
from ocr.safety import parse_data_url, safe_base64_decode
from ocr.rate_limit import check_rate_limit
from ocr.config import OCR_CONCURRENCY, VIEWER_BASE_URL, TRANSLATION_ENABLED, TRANSLATION_MODEL
from ocr.storage_config import ensure_storage_dirs, get_upload_dir, get_db_path
from ocr.storage import (
    _get_conn,
    _recover_interrupted,
    create_document,
    save_page_image,
    load_page_image,
    update_page_ocr,
    update_page_translation,
    update_translations_batch,
    set_status,
    get_document,
    get_status,
    get_pages,
    cleanup_old_documents,
    list_recent_documents,
)
from ocr.translate import translate_page

# Helper functions for file handling
SUFFIX_MAP = {
    ".pdf": ".pdf",
    ".docx": ".docx",
    ".png": ".png",
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
}

def _suffix_from_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return SUFFIX_MAP.get(f".{ext}", ".bin")

semaphore = asyncio.Semaphore(OCR_CONCURRENCY)
background_tasks: dict[str, asyncio.Task] = {}
logger = logging.getLogger("taia-ocr")

@asynccontextmanager
async def lifespan(app):
    # Startup
    conn = _get_conn()
    _recover_interrupted(conn)
    
    # Safety guard for SQLite
    import os
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))
    if workers > 1:
        raise RuntimeError(
            "SQLite storage is not safe with multiple workers. "
            "Set WEB_CONCURRENCY=1 or refactor to per-connection model."
        )
    
    cleanup_task = None
    shutdown_event = asyncio.Event()
    
    async def cleanup_loop():
        logger.info("[LIFESPAN] Background TTL cleanup loop started (run every 6 hours)")
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(6 * 3600)
                if shutdown_event.is_set():
                    break
                    
                start_time = time.time()
                deleted_count = await asyncio.to_thread(cleanup_old_documents)
                duration = time.time() - start_time
                
                logger.info(f"Cleanup run complete: {deleted_count} docs removed in {duration:.2f}s")
            except asyncio.CancelledError:
                logger.info("[LIFESPAN] Cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
                await asyncio.sleep(60)
    
    cleanup_task = asyncio.create_task(cleanup_loop())
    
    yield
    
    shutdown_event.set()
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
app = FastAPI(
    title="TAIA OCR Service",
    version="0.4.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Text Splitter ────────────────────────────────────────


def split_text_to_pages(text: str) -> list[str]:
    """Split extracted text into pages based on common page markers."""
    pages = re.split(r'\n*(?:#{1,3}\s*PAGE\s+\d+)\s*\n*', text, flags=re.IGNORECASE)
    if len(pages) > 1:
        return [p.strip() for p in pages if p.strip()]

    pages = re.split(r'\n*---\s*(?:PAGE|Page)\s+\d+\s*---\s*\n*', text)
    if len(pages) > 1:
        return [p.strip() for p in pages if p.strip()]

    pages = re.split(r'\n-{3,}\n', text)
    if len(pages) > 1:
        return [p.strip() for p in pages if p.strip()]

    return [text.strip()] if text.strip() else []


# ── Health ─────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check with storage validation."""
    import os
    import sqlite3
    
    # Check upload directory exists and is writable
    try:
        ensure_storage_dirs()
        upload_dir = get_upload_dir()
        if not os.path.isdir(upload_dir):
            return JSONResponse(
                status_code=500,
                content={"status": "error", "error": "Upload directory not accessible"}
            )
        # Test write permission
        test_file = os.path.join(upload_dir, ".health_check")
        try:
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "error": f"Upload directory not writable: {e}"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": f"Storage check failed: {e}"}
        )
    
    # Check database connection FIRST (initializes DB if needed)
    try:
        conn = _get_conn()
        conn.execute("SELECT 1")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": f"Database check failed: {e}"}
        )
    
    # Optional: verify file exists AFTER initialization
    if not os.path.isfile(get_db_path()):
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": "DB file missing after init"}
        )
    
    return {"status": "ok"}


# ── Mistral-compatible OCR (synchronous + creates viewer) ─


@app.post("/v1/ocr")
async def ocr_endpoint(request: Request):
    """Mistral OCR API compatible endpoint (synchronous).
    Also creates a viewer document as a side effect and starts background translation.
    """
    ip = request.client.host
    if not check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={
                "object": "error",
                "message": "Rate limit exceeded",
                "type": "rate_limit_error",
            },
        )

    body = await request.json()
    doc = body.get("document", {})
    raw = doc.get("document_url") or doc.get("image_url")

    if not raw:
        return JSONResponse(
            status_code=400,
            content={
                "object": "error",
                "message": "Missing document_url or image_url",
                "type": "invalid_request_error",
            },
        )

    try:
        data, suffix = parse_data_url(raw)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "object": "error",
                "message": f"Could not decode input: {e}",
                "type": "invalid_request_error",
            },
        )

    if not data:
        return JSONResponse(
            status_code=400,
            content={
                "object": "error",
                "message": "Could not decode input",
                "type": "invalid_request_error",
            },
        )

    # Max upload safeguard
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    if len(data) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": "File too large"}
        )

    async with semaphore:
        pages = await asyncio.to_thread(run_ocr, data, suffix)

    # ── Create viewer document as side effect ──────────────
    doc_id = None
    viewer_url = None

    try:
        # Determine title from suffix
        title = f"OCR Document"
        has_images = suffix in (".pdf", ".docx")

        # Split OCR text into pages
        page_texts = []
        for page in pages:
            page_texts.append(page.get("markdown", ""))

        total_pages = len(page_texts)
        if total_pages > 0:
            doc_id = create_document(
                title=title,
                filename=f"document{suffix}",
                total_pages=total_pages,
                has_images=has_images,
            )

            for i, text in enumerate(page_texts):
                update_page_ocr(doc_id, i, text, confidence=0.0)

            # Save page images if available (for source toggle)
            try:
                page_images = await asyncio.to_thread(extract_pages, data, suffix)
                for pg in page_images:
                    save_page_image(doc_id, pg["index"], pg["image"])
                del page_images
            except Exception:
                pass  # Non-critical — viewer works without source images

            # Start background translation if enabled
            if TRANSLATION_ENABLED:
                set_status(doc_id, "processing")
                task = asyncio.create_task(
                    _translate_document_background(doc_id, total_pages)
                )
                background_tasks[doc_id] = task
            else:
                set_status(doc_id, "complete")

            viewer_url = f"{VIEWER_BASE_URL}/view/{doc_id}"
            logger.info(
                f"[API] Viewer document {doc_id} created from /v1/ocr: "
                f"{total_pages} pages, translation={'on' if TRANSLATION_ENABLED else 'off'}"
            )
    except Exception as e:
        logger.error(f"[API] Failed to create viewer document from /v1/ocr: {e}")
        # Non-critical — OCR response still valid

    # ── Build Mistral-format response ─────────────────────
    response_pages = []
    for page in pages:
        p = {"index": page["index"], "markdown": page["markdown"]}
        if page.get("dimensions"):
            p["dimensions"] = page["dimensions"]
        response_pages.append(p)

    response = {
        "id": f"ocr-{uuid.uuid4().hex[:24]}",
        "model": "mistral-ocr-latest",
        "object": "ocr_response",
        "pages": response_pages,
    }

    # Include viewer info so LLM can find it
    if doc_id and viewer_url:
        response["document_id"] = doc_id
        response["viewer_url"] = viewer_url

    return response


# ── Async OCR (incremental, with background translation) ─


@app.post("/v1/ocr/async")
async def ocr_async_endpoint(request: Request):
    """Start async OCR processing. Returns immediately with doc_id and viewer URL."""
    ip = request.client.host
    if not check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={"status": "error", "error": "Rate limit exceeded"},
        )

    body = await request.json()
    raw_base64 = body.get("base64", "")
    filename = body.get("filename", "document.pdf")

    if not raw_base64:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "Missing base64 data"},
        )

    suffix = _suffix_from_filename(filename)
    try:
        data = safe_base64_decode(raw_base64)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": f"Failed to decode input: {e}"},
        )

    if not data:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "Could not decode input data"},
        )

    # Max upload safeguard
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    if len(data) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": "File too large"}
        )

    try:
        page_images = await asyncio.to_thread(extract_pages, data, suffix)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": f"Failed to extract pages: {e}"},
        )

    total_pages = len(page_images)
    if total_pages == 0:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "No pages found in document"},
        )

    title = filename.rsplit(".", 1)[0]
    doc_id = create_document(
        title=title,
        filename=filename,
        total_pages=total_pages,
        has_images=True,
    )

    for pg in page_images:
        save_page_image(doc_id, pg["index"], pg["image"])

    del page_images

    task = asyncio.create_task(_process_document_background(doc_id, total_pages))
    background_tasks[doc_id] = task

    viewer_url = f"{VIEWER_BASE_URL}/view/{doc_id}"

    logger.info(
        f"[API] Document {doc_id} queued: {total_pages} pages, "
        f"translation={'on' if TRANSLATION_ENABLED else 'off'}"
    )

    return {
        "status": "processing",
        "document_id": doc_id,
        "total_pages": total_pages,
        "viewer_url": viewer_url,
        "translation_enabled": TRANSLATION_ENABLED,
        "message": "Document queued. OCR and translation running in background.",
    }


async def _process_document_background(doc_id: str, total_pages: int):
    """Background task: OCR pages one by one, then translate if enabled."""
    logger.info(
        f"[Background] Starting processing for {doc_id} ({total_pages} pages, "
        f"translation={'on' if TRANSLATION_ENABLED else 'off'})"
    )

    for i in range(total_pages):
        try:
            img_bytes = load_page_image(doc_id, i)
            if not img_bytes:
                update_page_ocr(
                    doc_id, i, "[Error: page image not found]", confidence=0.0
                )
                continue

            async with semaphore:
                text = await asyncio.to_thread(ocr_single_page, img_bytes)

            update_page_ocr(doc_id, i, text, confidence=0.0)
            del img_bytes

            if TRANSLATION_ENABLED and text.strip():
                try:
                    translation = await translate_page(text)
                    update_page_translation(doc_id, i, translation)
                except Exception as e:
                    logger.error(
                        f"[Background] Translation failed for {doc_id} page {i}: {e}"
                    )
                    update_page_translation(doc_id, i, "")

        except Exception as e:
            logger.error(f"[Background] OCR failed for {doc_id} page {i}: {e}")
            update_page_ocr(doc_id, i, f"[OCR error: {e}]", confidence=0.0)

    status = get_status(doc_id)
    if status and status["status"] not in ("complete", "interrupted"):
        set_status(doc_id, "complete")

    logger.info(f"[Background] Processing complete for {doc_id}")
    background_tasks.pop(doc_id, None)


# ── Document from Text (with background translation) ─────


@app.post("/v1/documents/from-text")
async def create_document_from_text(request: Request):
    """Create a document from already-extracted text (no OCR needed).
    Starts background translation if TRANSLATION_ENABLED.
    """
    body = await request.json()
    text = body.get("text", "")
    filename = body.get("filename", "document.txt")
    title = body.get("title", "") or filename.rsplit(".", 1)[0]

    if not text:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "Missing text"},
        )

    # Max upload safeguard
    MAX_TEXT_SIZE = 50 * 1024 * 1024  # 50MB
    if len(text.encode('utf-8')) > MAX_TEXT_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": "Text too large"}
        )

    pages = split_text_to_pages(text)
    total_pages = len(pages)

    if total_pages == 0:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "No content after splitting"},
        )

    doc_id = create_document(
        title=title,
        filename=filename,
        total_pages=total_pages,
        has_images=False,
    )

    for i, page_text in enumerate(pages):
        update_page_ocr(doc_id, i, page_text, confidence=1.0)

    if TRANSLATION_ENABLED:
        set_status(doc_id, "processing")
        task = asyncio.create_task(_translate_document_background(doc_id, total_pages))
        background_tasks[doc_id] = task
    else:
        set_status(doc_id, "complete")

    viewer_url = f"{VIEWER_BASE_URL}/view/{doc_id}"

    logger.info(
        f"[API] Document {doc_id} created from text: {total_pages} pages, "
        f"translation={'on' if TRANSLATION_ENABLED else 'off'}"
    )

    return {
        "status": "processing" if TRANSLATION_ENABLED else "complete",
        "document_id": doc_id,
        "total_pages": total_pages,
        "viewer_url": viewer_url,
        "translation_enabled": TRANSLATION_ENABLED,
        "message": (
            "Document created. Translation running in background."
            if TRANSLATION_ENABLED
            else "Document created. No translation configured."
        ),
    }


async def _translate_document_background(doc_id: str, total_pages: int):
    """Background task: translate pages that already have OCR text."""
    logger.info(f"[Background] Starting translation for {doc_id} ({total_pages} pages)")

    for i in range(total_pages):
        try:
            # Fetch document state (read-only, can stay sync)
            doc = await asyncio.to_thread(get_document, doc_id)
            if not doc or i >= len(doc["pages"]):
                continue

            page = doc["pages"][i]
            if not page.get("ocr_done") or not page.get("ja", "").strip():
                # Skip pages without OCR text
                continue

            translation = await translate_page(page["ja"])
            
            await asyncio.to_thread(update_page_translation, doc_id, i, translation)
            logger.info(f"[Background] Saved translation for {doc_id} page {i} (len={len(translation)})")

        except Exception as e:
            logger.error(f"[Background] Translation failed for {doc_id} page {i}: {e}")
            # Only overwrite with empty if we're sure it failed
            await asyncio.to_thread(update_page_translation, doc_id, i, "")

    # Mark document complete
    status = await asyncio.to_thread(get_status, doc_id)
    if status and status["status"] not in ("complete", "interrupted"):
        await asyncio.to_thread(set_status, doc_id, "complete")

    logger.info(f"[Background] Translation complete for {doc_id}")
    background_tasks.pop(doc_id, None)


# ── Translation Push (manual override from LLM) ──────────


@app.post("/v1/documents/{doc_id}/translations")
async def push_translations(doc_id: str, request: Request):
    """Push translations from the LLM agent to the viewer.
    Body: {"pages": [{"page_num": 0, "en": "translated text"}, ...]}
    """
    doc = get_document(doc_id)
    if not doc:
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    pages = body.get("pages", [])

    if not pages:
        return JSONResponse(
            {"status": "error", "error": "No pages provided"},
            status_code=400,
        )

    update_translations_batch(doc_id, pages)

    status = get_status(doc_id)
    return {
        "status": "ok",
        "document_id": doc_id,
        "translation_progress": status["translation_progress"] if status else 0,
        "total_pages": status["total_pages"] if status else 0,
    }


# ── List Recent Documents ────────────────────────────────


@app.get("/v1/documents")
async def list_documents(limit: int = 10):
    """List recent documents. Used by MCP tool find_document."""
    docs = list_recent_documents(limit)
    return {"documents": docs}


# ── Side-by-side viewer creation ─────────────────────────


@app.post("/v1/view")
async def create_view(data: dict):
    """Create a viewer from pre-existing text (for create_side_by_side_viewer MCP tool)."""
    doc_id = create_document(
        title=data.get("title", "Document"),
        filename="paste.md",
        total_pages=1,
        has_images=False,
    )
    update_page_ocr(doc_id, 0, data.get("japanese", ""), confidence=1.0)
    if data.get("english"):
        update_page_translation(doc_id, 0, data["english"])
    set_status(doc_id, "complete")
    return {"viewer_url": f"{VIEWER_BASE_URL}/view/{doc_id}"}


# ── Viewer Endpoints ─────────────────────────────────────


@app.get("/view/{doc_id}")
async def view_doc(doc_id: str):
    """Serve the viewer HTML."""
    try:
        with open("static/viewer.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        logger.error("Viewer HTML not found: static/viewer.html")
        return JSONResponse(
            status_code=500,
            content={"error": "Viewer template missing"}
        )


@app.get("/view/{doc_id}/status")
async def view_status(doc_id: str):
    """Progress status for incremental loading."""
    status = get_status(doc_id)
    if status:
        return JSONResponse(status)
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/view/{doc_id}/pages")
async def view_pages_endpoint(doc_id: str, start: int = 0, end: int = -1):
    """Fetch completed pages for progressive rendering."""
    doc = get_document(doc_id)
    if not doc:
        return JSONResponse({"error": "not found"}, status_code=404)

    total = doc["metadata"]["total_pages"]
    end_val = total if end == -1 else min(end, total)
    pages = get_pages(doc_id, start, end_val)
    return JSONResponse({
        "doc_id": doc_id,
        "total_pages": total,
        "pages": pages,
    })


@app.get("/view/{doc_id}/pages/{page_num}/image")
async def view_page_image(doc_id: str, page_num: int):
    """Serve a page's source image (the original screenshot/scan)."""
    img_bytes = load_page_image(doc_id, page_num)
    if not img_bytes:
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(content=img_bytes, media_type="image/png")


@app.get("/view/{doc_id}/data")
async def view_data(doc_id: str):
    """Full document data (backward compat)."""
    doc = get_document(doc_id)
    if not doc:
        return JSONResponse({"error": "not found"}, status_code=404)

    status = get_status(doc_id)
    pages = doc["pages"]

    ja_full = "\n\n".join(p["ja"] for p in pages if p.get("ocr_done"))
    en_full = "\n\n".join(p["en"] for p in pages if p.get("translation_done"))

    return JSONResponse({
        "ja": ja_full,
        "en": en_full,
        "title": status["title"],
        "total_pages": status["total_pages"],
        "ocr_progress": status["ocr_progress"],
        "translation_progress": status["translation_progress"],
        "status": status["status"],
        "has_images": status["has_images"],
        "translation_enabled": TRANSLATION_ENABLED,
        "pages": [p for p in pages if p.get("ocr_done")],
    })