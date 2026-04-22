"""
Document storage layer — SQLite-backed.
- Metadata + page text: SQLite (uploads/ocr.db)
- Page images: on disk (uploads/{doc_id}/page_NNNN.png)

Survives server restarts. Interrupted documents are marked on recovery.
Translation is pushed by the LLM agent, not generated server-side.
"""
import sqlite3
import uuid
import shutil
import logging
import time
import asyncio
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from threading import Lock

from .storage_config import (
    get_upload_dir,
    get_db_path,
    safe_write,
    ensure_storage_dirs,
    DOCUMENT_CLEANUP_HOURS,
)

logger = logging.getLogger("taia-ocr")
logger.info(f"[STORAGE INIT] DB={get_db_path()} UPLOADS={get_upload_dir()}")

_lock = Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn

    if _conn is not None:
        try:
            _conn.execute("SELECT 1")
            return _conn
        except sqlite3.ProgrammingError:
            # Connection is dead → reset
            _conn = None
        except sqlite3.OperationalError:
            _conn = None

    ensure_storage_dirs()

    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"[STORAGE] Using DB at: {db_path}")

    conn = sqlite3.connect(
        str(db_path),
        # WARNING:
        # check_same_thread=False is safe ONLY under single-worker deployment.
        # Multiple workers WILL corrupt the SQLite database.
        check_same_thread=False,
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    # MUST be set before tables exist
    conn.execute("PRAGMA auto_vacuum = FULL")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys=ON")

    _init_db(conn)

    _conn = conn
    return _conn


@contextmanager
def transaction_scope(conn: sqlite3.Connection):
    """
    Transaction context manager with BEGIN IMMEDIATE.
    Commits on success, rolls back on exception.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield
        conn.commit()
        logger.debug("DB transaction committed")
    except Exception as e:
        conn.rollback()
        logger.error(f"DB transaction rolled back: {e}")
        raise


def _init_db(conn: sqlite3.Connection):
    conn.execute("PRAGMA auto_vacuum = FULL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            total_pages INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'processing',
            ocr_progress INTEGER DEFAULT 0,
            translation_progress INTEGER DEFAULT 0,
            has_images INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pages (
            doc_id TEXT NOT NULL,
            page_num INTEGER NOT NULL,
            ja TEXT DEFAULT '',
            en TEXT DEFAULT '',
            ocr_done INTEGER DEFAULT 0,
            translation_done INTEGER DEFAULT 0,
            confidence REAL DEFAULT 0.0,
            PRIMARY KEY (doc_id, page_num)
        );
    """)
    conn.commit()


def _recover_interrupted(conn: sqlite3.Connection):
    """Mark documents that were mid-processing when the server stopped."""
    result = conn.execute(
        "SELECT doc_id FROM documents WHERE status = 'processing'"
    ).fetchall()
    if result:
        conn.execute(
            "UPDATE documents SET status = 'interrupted' WHERE status = 'processing'"
        )
        conn.commit()
        for row in result:
            logger.warning(
                f"[Storage] Document {row['doc_id']} marked as interrupted"
            )


def _upload_dir() -> Path:
    """Get the upload directory (always fresh from config)."""
    return get_upload_dir()


def create_document(
    title: str,
    filename: str,
    total_pages: int,
    has_images: bool = False,
) -> str:
    """Create a new document entry. Returns doc_id."""
    doc_id = uuid.uuid4().hex[:8]
    doc_dir = _upload_dir() / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    
    with _lock:
        conn = _get_conn()
        with transaction_scope(conn):
            conn.execute(
                """INSERT INTO documents
                   (doc_id, title, filename, total_pages, created_at, has_images)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (doc_id, title, filename, total_pages, now, int(has_images)),
            )
            conn.executemany(
                "INSERT INTO pages (doc_id, page_num) VALUES (?, ?)",
                [(doc_id, i) for i in range(total_pages)],
            )
    
    logger.info(f"[Storage] Created document {doc_id}: {total_pages} pages")
    return doc_id


def save_page_image(doc_id: str, page_num: int, image_bytes: bytes) -> str:
    """Save a page image to disk. Returns file path."""
    doc_dir = _upload_dir() / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    path = doc_dir / f"page_{page_num:04d}.png"
    safe_write(str(path), image_bytes)
    return str(path)


def load_page_image(doc_id: str, page_num: int) -> bytes | None:
    """Load a page image from disk."""
    path = _upload_dir() / doc_id / f"page_{page_num:04d}.png"
    if not path.exists():
        logger.warning(f"[Storage] Missing image: {path}")
        return None
    return path.read_bytes()


def update_page_ocr(doc_id: str, page_num: int, text: str, confidence: float = 0.0):
    """Update OCR result for a page."""
    with _lock:
        conn = _get_conn()
        with transaction_scope(conn):
            conn.execute(
                "UPDATE pages SET ja = ?, ocr_done = 1, confidence = ? WHERE doc_id = ? AND page_num = ?",
                (text, confidence, doc_id, page_num),
            )

            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM pages WHERE doc_id = ? AND ocr_done = 1",
                (doc_id,),
            ).fetchone()
            ocr_progress = row["cnt"]

            doc = conn.execute(
                "SELECT total_pages FROM documents WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()

            if doc:
                total_pages = doc["total_pages"]
                if ocr_progress >= total_pages:
                    conn.execute(
                        "UPDATE documents SET ocr_progress = ?, status = 'complete' WHERE doc_id = ?",
                        (ocr_progress, doc_id),
                    )
                    logger.info(f"[Storage] OCR complete for {doc_id}")
                else:
                    conn.execute(
                        "UPDATE documents SET ocr_progress = ? WHERE doc_id = ?",
                        (ocr_progress, doc_id),
                    )


def update_page_translation(doc_id: str, page_num: int, text: str):
    """Update translation for a page (pushed by LLM agent)."""
    with _lock:
        conn = _get_conn()
        with transaction_scope(conn):
            logger.debug(f"[DB] UPDATE pages SET en (len={len(text)}) WHERE doc_id={doc_id} page={page_num}")
            result = conn.execute(
                "UPDATE pages SET en = ?, translation_done = 1 WHERE doc_id = ? AND page_num = ?",
                (text, doc_id, page_num),
            )
            logger.debug(f"[DB] Rows affected: {result.rowcount}")
            
            # Update progress counter
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM pages WHERE doc_id = ? AND translation_done = 1",
                (doc_id,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE documents SET translation_progress = ? WHERE doc_id = ?",
                    (row["cnt"], doc_id),
                )
    logger.info(f"[Storage] Translation updated for {doc_id} page {page_num}")


def update_translations_batch(doc_id: str, pages: list[dict]):
    """Update translations for multiple pages at once (pushed by LLM agent)."""
    with _lock:
        conn = _get_conn()
        for p in pages:
            page_num = p.get("page_num")
            text = p.get("en", "")
            if page_num is not None:
                conn.execute(
                    "UPDATE pages SET en = ?, translation_done = 1 WHERE doc_id = ? AND page_num = ?",
                    (text, doc_id, page_num),
                )

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM pages WHERE doc_id = ? AND translation_done = 1",
            (doc_id,),
        ).fetchone()
        trans_progress = row["cnt"]

        conn.execute(
            "UPDATE documents SET translation_progress = ? WHERE doc_id = ?",
            (trans_progress, doc_id),
        )
        conn.commit()

    logger.info(
        f"[Storage] Batch translation for {doc_id}: {len(pages)} pages ({trans_progress} total)"
    )


def set_status(doc_id: str, status: str):
    """Set document status directly."""
    with _lock:
        conn = _get_conn()
        with transaction_scope(conn):
            conn.execute(
                "UPDATE documents SET status = ? WHERE doc_id = ?",
                (status, doc_id),
            )


def get_document(doc_id: str) -> dict | None:
    """Get full document (metadata + pages). Returns a copy."""
    with _lock:
        conn = _get_conn()
        doc = conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,),
        ).fetchone()

        if not doc:
            return None

        pages = conn.execute(
            "SELECT * FROM pages WHERE doc_id = ? ORDER BY page_num",
            (doc_id,),
        ).fetchall()

        return {
            "metadata": {
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "filename": doc["filename"],
                "total_pages": doc["total_pages"],
                "created_at": doc["created_at"],
                "status": doc["status"],
                "ocr_progress": doc["ocr_progress"],
                "translation_progress": doc["translation_progress"],
                "has_images": bool(doc["has_images"]),
            },
            "pages": [
                {
                    "page_num": p["page_num"],
                    "ja": p["ja"],
                    "en": p["en"],
                    "ocr_done": bool(p["ocr_done"]),
                    "translation_done": bool(p["translation_done"]),
                    "confidence": p["confidence"],
                }
                for p in pages
            ],
        }


def get_status(doc_id: str) -> dict | None:
    """Get document metadata/status only."""
    with _lock:
        conn = _get_conn()
        doc = conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,),
        ).fetchone()

        if not doc:
            return None

        return {
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "filename": doc["filename"],
            "total_pages": doc["total_pages"],
            "created_at": doc["created_at"],
            "status": doc["status"],
            "ocr_progress": doc["ocr_progress"],
            "translation_progress": doc["translation_progress"],
            "has_images": bool(doc["has_images"]),
        }


def get_pages(doc_id: str, start: int = 0, end: int | None = None) -> list[dict]:
    """Get a range of pages. Returns copies."""
    with _lock:
        conn = _get_conn()

        if end is None:
            rows = conn.execute(
                "SELECT * FROM pages WHERE doc_id = ? AND page_num >= ? ORDER BY page_num",
                (doc_id, start),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pages WHERE doc_id = ? AND page_num >= ? AND page_num < ? ORDER BY page_num",
                (doc_id, start, end),
            ).fetchall()

        return [
            {
                "page_num": p["page_num"],
                "ja": p["ja"],
                "en": p["en"],
                "ocr_done": bool(p["ocr_done"]),
                "translation_done": bool(p["translation_done"]),
                "confidence": p["confidence"],
            }
            for p in rows
        ]


def cleanup_document(doc_id: str):
    """Remove document from database and disk."""
    with _lock:
        conn = _get_conn()
        with transaction_scope(conn):
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    
    logger.debug(f"DB committed. Proceeding with file deletion for doc {doc_id}")
    
    doc_dir = _upload_dir() / doc_id
    if doc_dir.exists():
        shutil.rmtree(doc_dir, ignore_errors=True)

def list_recent_documents(limit: int = 10) -> list[dict]:
    """List recent documents, newest first. Returns metadata only."""
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT doc_id, title, filename, total_pages, created_at, status, "
            "ocr_progress, translation_progress, has_images "
            "FROM documents ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [
            {
                "doc_id": r["doc_id"],
                "title": r["title"],
                "filename": r["filename"],
                "total_pages": r["total_pages"],
                "created_at": r["created_at"],
                "status": r["status"],
                "ocr_progress": r["ocr_progress"],
                "translation_progress": r["translation_progress"],
                "has_images": bool(r["has_images"]),
            }
            for r in rows
        ]
    
def cleanup_old_documents():
    """Remove documents older than DOCUMENT_CLEANUP_HOURS."""
    now = datetime.utcnow()
    ttl_seconds = DOCUMENT_CLEANUP_HOURS * 3600

    logger.warning(f"[CLEANUP] NOW={now.isoformat()}")

    with _lock:
        conn = _get_conn()

        rows = conn.execute(
            "SELECT doc_id, created_at, status FROM documents"
        ).fetchall()

        to_remove = []

        for row in rows:
            try:
                raw = row["created_at"]

                logger.warning(
                    f"[CLEANUP] doc_id={row['doc_id']} "
                    f"created_at_raw={row['created_at']} "
                )

                if raw.endswith("Z"):
                    raw = raw[:-1]

                dt = datetime.fromisoformat(raw)

                logger.warning(
                    f"[CLEANUP] parsed_dt={dt.isoformat()} "
                )

                dt = dt.replace(microsecond=0)
                age_seconds = (now.replace(microsecond=0) - dt).total_seconds()
                
                logger.warning(
                    f"[CLEANUP] age_seconds={age_seconds} ttl={ttl_seconds}"
                )

                # Skip processing documents only if they are still within TTL
                # (they may be actively running). If they are past TTL, they are
                # stuck/interrupted and must be cleaned up.
                if row["status"] == "processing" and age_seconds < ttl_seconds:
                    continue

                if age_seconds >= ttl_seconds:
                    logger.warning(f"[CLEANUP] MARK DELETE {row['doc_id']}")
                    to_remove.append(row["doc_id"])

            except (ValueError, TypeError):
                continue

        # Delete phase 1: Database (atomic)
        for doc_id in to_remove:
            try:
                # delete pages first (FK safe)
                conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
                conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            except Exception as e:
                logger.error(f"[Storage] DB delete failed for {doc_id}: {e}")

        conn.commit()

        # Delete phase 2: Files (non-critical, can be retried later)
        for doc_id in to_remove:
            try:
                doc_dir = _upload_dir() / doc_id
                if doc_dir.exists():
                    shutil.rmtree(doc_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"[Storage] File delete failed for {doc_id}: {e}")

    logger.warning("[CLEANUP] COMMIT COMPLETE")
