"""
TAIA OCR — VLM-based pipeline (Qwen3-VL).

Replaces the PaddleOCR + spatial-reconstruction approach entirely.
Each page image is sent directly to the vision model; the model returns
structured markdown natively — no bounding boxes, no column heuristics.

Backends (configured via env vars, identical API surface):
  VLM_BACKEND=ollama  →  local Ollama for development/testing
  VLM_BACKEND=vllm    →  vLLM for production
"""

import base64
import io
import re
import unicodedata
import logging
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

from .model import get_client
from .config import (
    VLM_MODEL,
    VLM_MAX_TOKENS,
    VLM_OCR_CONCURRENCY,
    ENABLE_UNICODE_NORMALIZE,
    STRIP_OCR_ARTIFACTS,
    JOIN_HYPHENATED_WORDS,
)

logger = logging.getLogger("taia-ocr")

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a precise OCR engine specialised in Japanese and mixed "
    "Japanese/English technical documents including Pro*C, Oracle SQL, "
    "and C programming manuals. "
    "Your sole task is to convert document page images to clean, "
    "well-structured markdown. Never translate. Never explain. "
    "Output markdown only."
)

_USER_PROMPT = """\
Convert this document page image to markdown. Follow every rule exactly.

STRUCTURE RULES:
1. Transcribe ALL visible text verbatim — every kanji, hiragana, katakana,
   and every Latin character exactly as it appears.
2. Table of contents / index pages → render each entry as a list item:
   `- Chapter title .... page number`
3. Data tables with rows and columns → proper markdown tables with
   a header row and |---|---| separator row.
4. ANY code listing, SQL statement, Pro*C statement, shell command,
   or C/C++ source fragment → MUST be in a fenced code block.
   Use the correct language tag: sql, c, bash, python, or text.
   Each statement goes on its own line inside the fence.
   EXEC SQL statements must NEVER appear as inline prose.
5. Section headings → ## heading or ### heading as appropriate.
6. Bullet or numbered lists → - item or 1. item format.
7. Paragraphs of prose → separated by a single blank line.

EXAMPLES — These show the exact formatting expected:

Example 1: Simple EXEC SQL
```sql
EXEC SQL WHENEVER SQLERROR GOTO sql_err;
```
If an SQL error occurs, jump to the sql_err label.

Example 2: Pro*C variable declaration + SQL
```c
EXEC SQL BEGIN DECLARE SECTION;
    char hv_koza_status[2];
EXEC SQL END DECLARE SECTION;
```

Example 3: Full Pro*C embedded SQL
```c
EXEC SQL SELECT account_status
    INTO :hv_koza_status
    FROM customer_information
    WHERE account_number = '0000001';
```

Example 4: Error handling in Pro*C
```c
sql_err:
    printf("SQL error occurred\\n");
    exit(1);
```

Example 5: Japanese TOC page
```markdown
## 目次

- 第一章 Pro*Cの基本 .................... 1
  - 1 組み込みSQL ....................... 2
  - 2 ホスト変数 ........................ 5
- 第二章 Makeコマンドとmakefile ........ 10
- 第三章 Pro*C応用 ..................... 15
```

CRITICAL — CODE BLOCK RULE:
If you see ANY of the following, it is code and must go in a fenced block:
- Lines starting with EXEC SQL
- Lines starting with SELECT, INSERT, UPDATE, DELETE, CONNECT, FETCH,
  OPEN, CLOSE, COMMIT, ROLLBACK, BEGIN, END, DECLARE, WHENEVER
- C function calls: printf, sprintf, fprintf, strlen, strcpy, etc.
- Variable declarations: int, char, long, float, double, VARCHAR
- Lines ending with ; or {
- Lines containing exit(1), return, goto, or label names ending with :

Output ONLY the markdown — no preamble, no commentary, no explanation.
"""

# ── Thinking-token filter (Qwen3 may emit <think>…</think>) ──────────────────

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


# ── Minimal post-processing ───────────────────────────────────────────────────
# Does NOT touch markdown structure — only fixes unicode and stray OCR symbols.

_ARTIFACT_PATTERNS = [
    (re.compile(r"[─━]+ "),                    " "),
    (re.compile(r"[│┃┆┇┊┋]+ "),               " "),
    (re.compile(r"^\s*[•‧]+(?=\s*$)", re.M),  " "),
    (re.compile(r"\n{3,}"),                     "\n\n"),
]
_HYPHEN_BREAK = re.compile(r"(\w)[-‐‑]\s*\n\s*(\w)")


def clean_ocr_text(
    raw: str,
    *,
    normalize: bool = True,
    strip_artifacts: bool = True,
    join_hyphenated: bool = True,
) -> str:
    text = raw
    if normalize:
        text = unicodedata.normalize("NFKC", text)
    if join_hyphenated:
        text = _HYPHEN_BREAK.sub(r"\1\2", text)
    if strip_artifacts:
        for pattern, replacement in _ARTIFACT_PATTERNS:
            text = pattern.sub(replacement, text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text.strip()


# ── Image encoding ────────────────────────────────────────────────────────────

# Cap longest edge before encoding to keep payload size sane.
# 1920px is sufficient for Qwen3-VL; higher adds latency with no quality gain.
_MAX_IMAGE_EDGE = 1920


def _image_to_base64(img_bytes: bytes) -> str:
    """
    Resize (if needed) and base64-encode a page image as JPEG.
    Resizing is aspect-ratio preserving and only downscales, never upscales.
    JPEG is used to minimize network payload size to the VLM.
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    w, h = img.size
    if max(w, h) > _MAX_IMAGE_EDGE:
        scale = _MAX_IMAGE_EDGE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ── VLM call ──────────────────────────────────────────────────────────────────

def _call_vlm(img_bytes: bytes) -> str:
    """
    POST the page image to /v1/chat/completions and return the raw text.
    Raises httpx.HTTPStatusError on non-2xx; returns "" on empty content.
    """
    client = get_client()
    b64    = _image_to_base64(img_bytes)

    payload = {
        "model": VLM_MODEL,
        "messages":[
            {
                "role": "system",
                "content": _SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content":[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": _USER_PROMPT,
                    },
                ],
            },
        ],
        "max_tokens": VLM_MAX_TOKENS,
        "temperature": 0.0,
        "stream": False,
    }

    resp = client.post("/v1/chat/completions", json=payload)
    resp.raise_for_status()

    content = (
        resp.json()
        .get("choices",[{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return content or ""


# ── Public API ────────────────────────────────────────────────────────────────

def ocr_image_bytes_with_conf(img_bytes: bytes) -> Tuple[str, float]:
    """
    OCR one page via the VLM.
    Returns (markdown_text, confidence).
    Confidence is always 1.0 — VLMs do not expose per-token scores.
    """
    try:
        raw     = _call_vlm(img_bytes)
        raw     = _strip_thinking(raw)

        if not raw.strip():
            logger.warning("VLM returned empty response")
            return ("", 0.0)

        cleaned = clean_ocr_text(
            raw,
            normalize=ENABLE_UNICODE_NORMALIZE,
            strip_artifacts=STRIP_OCR_ARTIFACTS,
            join_hyphenated=JOIN_HYPHENATED_WORDS,
        )
        logger.debug("VLM OCR: %d chars", len(cleaned))
        return (cleaned, 1.0)

    except httpx.HTTPError as e:
        logger.error("VLM HTTP error: %s", e)
        # Fail-fast on connection and timeout errors to avoid cascading deadlocks
        if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)):
            raise RuntimeError(f"VLM backend unreachable or timed out: {e}") from e
        return ("", 0.0)
    except Exception:
        logger.error("VLM OCR failed", exc_info=True)
        return ("", 0.0)


def ocr_image_bytes(img_bytes: bytes) -> str:
    """OCR one page. Returns markdown text."""
    text, _ = ocr_image_bytes_with_conf(img_bytes)
    return text


def ocr_pages_batch(page_images: list[tuple[bytes, int, int]]) -> list[str]:
    """
    OCR multiple pages.
    Utilizes ThreadPoolExecutor for concurrent page processing if configured.
    """
    total   = len(page_images)
    results = [""] * total

    def _process(idx: int, img_data: bytes, width: int, height: int) -> tuple[int, str]:
        logger.info("OCR page %d/%d  (%d×%d px)", idx, total, width, height)
        return idx, ocr_image_bytes(img_data)

    if VLM_OCR_CONCURRENCY > 1:
        with ThreadPoolExecutor(max_workers=VLM_OCR_CONCURRENCY) as executor:
            futures =[
                executor.submit(_process, i, img_bytes, w, h)
                for i, (img_bytes, w, h) in enumerate(page_images, start=1)
            ]
            for future in futures:
                try:
                    idx, text = future.result()
                    results[idx - 1] = text
                except Exception:
                    # Cancel remaining tasks to prevent thread lockup during fail-fast
                    for f in futures:
                        f.cancel()
                    raise
    else:
        for i, (img_bytes, w, h) in enumerate(page_images, start=1):
            idx, text = _process(i, img_bytes, w, h)
            results[idx - 1] = text

    return results


def process_ocr_result(ocr_result) -> str:
    """Backward-compatible passthrough for external OCR results."""
    if isinstance(ocr_result, str):
        return clean_ocr_text(ocr_result)
    return ""


def get_image_info(img_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) of an image."""
    try:
        return Image.open(io.BytesIO(img_bytes)).size
    except Exception:
        return (0, 0)