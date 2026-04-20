import tempfile
import os
from .core import ocr_image_bytes, get_image_info
from .docx import extract_docx_images
from .config import MAX_FILE_SIZE, PDF_RENDER_DPI


def extract_pages(data: bytes, suffix: str) -> list[dict]:
    """
    Extract page images from a document. NO OCR — fast.
    Returns: [{"index": 0, "image": bytes, "width": int, "height": int}, ...]
    """
    if len(data) > MAX_FILE_SIZE:
        return []

    if suffix in (".png", ".jpg", ".jpeg", ".webp"):
        w, h = get_image_info(data)
        return [{"index": 0, "image": data, "width": w, "height": h}]

    if suffix == ".pdf":
        return _extract_pdf_pages(data)

    if suffix == ".docx":
        return _extract_docx_pages(data)

    return []


def _extract_pdf_pages(data: bytes) -> list[dict]:
    try:
        import fitz
    except ImportError:
        return []

    pages = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        for i in range(len(doc)):
            page = doc[i]
            pix = page.get_pixmap(dpi=PDF_RENDER_DPI)
            img_bytes = pix.tobytes("png")
            pages.append({
                "index": i,
                "image": img_bytes,
                "width": pix.width,
                "height": pix.height,
            })
        doc.close()
    except Exception:
        pass

    return pages


def _extract_docx_pages(data: bytes) -> list[dict]:
    images = extract_docx_images(data)
    return [
        {
            "index": i,
            "image": img["image"],
            "width": img["width"],
            "height": img["height"],
        }
        for i, img in enumerate(images)
    ]


def ocr_single_page(img_bytes: bytes) -> str:
    """OCR a single page image. Returns extracted text."""
    return ocr_image_bytes(img_bytes)


def run_ocr(data: bytes, suffix: str) -> list[dict]:
    """
    OCR a document (backward compatible — processes all pages at once).
    Returns: [{"index": 0, "markdown": "...", "dimensions": {...}}, ...]
    """
    page_images = extract_pages(data, suffix)

    if not page_images:
        if len(data) > MAX_FILE_SIZE:
            return [{"index": 0, "markdown": "File too large.", "dimensions": None}]
        return [
            {"index": 0, "markdown": f"Unsupported format: {suffix}", "dimensions": None}
        ]

    results = []
    for pg in page_images:
        text = ocr_single_page(pg["image"])
        w, h = pg.get("width", 0), pg.get("height", 0)
        results.append({
            "index": pg["index"],
            "markdown": text,
            "dimensions": {"dpi": PDF_RENDER_DPI, "height": h, "width": w} if w > 0 else None,
        })

    return results