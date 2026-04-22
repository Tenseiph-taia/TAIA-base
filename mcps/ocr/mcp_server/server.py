import asyncio
import base64
import requests
from mcp.server.fastmcp import FastMCP

from ocr.core import ocr_image_bytes
from ocr.rate_limit import check_rate_limit
from ocr.config import VLM_OCR_CONCURRENCY, API_BASE_URL

mcp = FastMCP("TAIA-OCR", host="0.0.0.0", port=8003)
semaphore = asyncio.Semaphore(VLM_OCR_CONCURRENCY)


def _strip_data_url(data: str) -> str:
    """Extract raw base64 from a data URL if present."""
    if data.startswith("data:"):
        comma_idx = data.find(",")
        if comma_idx != -1:
            return data[comma_idx + 1:]
    return data


@mcp.tool()
def find_document(title: str = "") -> str:
    """Find a recently processed document. Use this when LibreChat has already OCR'd
    the document and you need to find the viewer URL. Call this FIRST before any other tool.
    Optionally filter by title (partial match, case-insensitive).
    The document was automatically created when LibreChat processed the upload."""
    try:
        params = {"limit": 5}
        resp = requests.get(
            f"{API_BASE_URL}/v1/documents",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        docs = data.get("documents", [])
        if not docs:
            return "No documents found. Use create_document_from_text if you have text to create one."

        # Filter by title if provided
        if title:
            title_lower = title.lower()
            matches = [
                d for d in docs
                if title_lower in d["title"].lower() or title_lower in d["filename"].lower()
            ]
            if matches:
                docs = matches

        lines = []
        for d in docs[:5]:
            doc_id = d["doc_id"]
            lines.append(
                f"ID: {doc_id} | Title: {d['title']} | "
                f"Pages: {d['total_pages']} | "
                f"OCR: {d['ocr_progress']}/{d['total_pages']} | "
                f"Translation: {d['translation_progress']}/{d['total_pages']} | "
                f"Status: {d['status']} | "
                f"Viewer: {API_BASE_URL}/view/{doc_id}"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def ocr_document(
    document_base64: str,
    filename: str = "document.pdf",
) -> str:
    """OCR a PDF/DOCX/PNG from base64 data. Use ONLY when the document is image-only
    and no text was extracted by LibreChat. Returns doc_id and viewer URL.
    OCR and translation run in the background — share the viewer URL with the user immediately."""

    if not check_rate_limit("mcp"):
        return "Rate limit exceeded"

    raw_base64 = _strip_data_url(document_base64)

    try:
        resp = requests.post(
            f"{API_BASE_URL}/v1/ocr/async",
            json={
                "base64": raw_base64,
                "filename": filename,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("status") == "error":
            return f"Error: {result.get('error', 'Unknown error')}"

        doc_id = result["document_id"]
        viewer_url = result["viewer_url"]
        total = result["total_pages"]
        trans = result.get("translation_enabled", False)

        return (
            f"Document queued for OCR.\n"
            f"Document ID: {doc_id}\n"
            f"Total pages: {total}\n"
            f"Translation: {'auto' if trans else 'disabled'}\n"
            f"Viewer URL: {viewer_url}\n"
            f"Share the viewer URL with the user."
        )
    except requests.exceptions.RequestException as e:
        return f"Error communicating with OCR server: {e}"


@mcp.tool()
def create_document_from_text(
    japanese_text: str,
    filename: str = "document.txt",
    title: str = "",
) -> str:
    """Create a document from Japanese text. ONLY use for small documents (under 3000 chars).
    For large documents already processed by LibreChat, use find_document() instead —
    the viewer is created automatically when LibreChat OCRs the file."""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/v1/documents/from-text",
            json={
                "text": japanese_text,
                "filename": filename,
                "title": title or filename.rsplit(".", 1)[0],
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("status") == "error":
            return f"Error: {result.get('error', 'Unknown error')}"

        doc_id = result["document_id"]
        viewer_url = result["viewer_url"]
        total = result["total_pages"]
        trans = result.get("translation_enabled", False)

        return (
            f"Document created.\n"
            f"Document ID: {doc_id}\n"
            f"Total pages: {total}\n"
            f"Translation: {'auto' if trans else 'disabled'}\n"
            f"Viewer URL: {viewer_url}\n"
            f"Share the viewer URL with the user."
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_document_status(document_id: str) -> str:
    """Check the processing status of a document."""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/view/{document_id}/status",
            timeout=10,
        )
        resp.raise_for_status()
        status = resp.json()

        if "error" in status:
            return f"Document {document_id} not found"

        lines = [
            f"Document: {status.get('title', 'Unknown')}",
            f"Status: {status.get('status', 'unknown')}",
            f"OCR: {status.get('ocr_progress', 0)}/{status.get('total_pages', 0)} pages",
            f"Translation: {status.get('translation_progress', 0)}/{status.get('total_pages', 0)} pages",
            f"Viewer: {API_BASE_URL}/view/{document_id}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_document_pages(
    document_id: str,
    start_page: int = 0,
    end_page: int = -1,
) -> str:
    """Retrieve specific pages from a document.
    Pages are 0-indexed. Use end_page=-1 for all pages."""
    try:
        params = {"start": start_page, "end": end_page}
        resp = requests.get(
            f"{API_BASE_URL}/view/{document_id}/pages",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            return f"Document {document_id} not found"

        pages = data.get("pages", [])
        if not pages:
            return "No pages ready in the requested range"

        result_lines = []
        for p in pages:
            num = p.get("page_num", 0) + 1
            result_lines.append(f"--- Page {num} ---")
            if p.get("ja"):
                result_lines.append(f"[JA] {p['ja']}")
            if p.get("translation_done") and p.get("en"):
                result_lines.append(f"[EN] {p['en']}")
            elif p.get("ocr_done"):
                result_lines.append(f"[EN] (translation in progress)")
            else:
                result_lines.append(f"[EN] (not yet processed)")
            result_lines.append("")

        total = data.get("total_pages", 0)
        first = pages[0].get("page_num", 0) + 1
        last = pages[-1].get("page_num", 0) + 1
        header = f"Pages {first}-{last} of {total}\n\n"
        return header + "\n".join(result_lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def update_document_translations(
    document_id: str,
    pages: list[dict],
) -> str:
    """Manually push English translations. ONLY use when automatic translation is disabled
    or you want to override a specific page."""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/v1/documents/{document_id}/translations",
            json={"pages": pages},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("error"):
            return f"Error: {result['error']}"

        return (
            f"Translations updated. "
            f"Progress: {result.get('translation_progress', 0)}/{result.get('total_pages', 0)} pages."
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def extract_text_from_url_screenshot(
    screenshot_base64: str,
    source_url: str = "",
) -> str:
    """OCR a screenshot. Provide the image as base64."""
    if not check_rate_limit("mcp"):
        return "Rate limit exceeded"

    img = base64.b64decode(screenshot_base64)
    async with semaphore:
        text = await asyncio.to_thread(ocr_image_bytes, img)
    return text or "No text found"


@mcp.tool()
def create_side_by_side_viewer(
    japanese_markdown: str,
    english_markdown: str,
    title: str = "Document",
) -> str:
    """Create a viewer from small inline text (under 1000 chars).
    For documents, use find_document() or create_document_from_text()."""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/v1/view",
            json={
                "japanese": japanese_markdown,
                "english": english_markdown,
                "title": title,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("viewer_url", "Error: no URL returned")
    except Exception as e:
        return f"Error: {e}"