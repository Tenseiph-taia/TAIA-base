"""
Post-translation text sanitization.

LLMs sometimes add preamble ("Here is the translation:"), trailing
notes, unbalanced code fences, or broken table separators — all of
which break marked.parse() in the viewer.

This module strips those artefacts and validates structural markdown.
"""

import logging
import re
import unicodedata

from .config import ENABLE_POST_TRANSLATION_SANITIZE

logger = logging.getLogger("taia-ocr")


# ── Commentary patterns ──────────────────────────────────────

_PREAMBLE_PATTERNS = [
    re.compile(
        r"^(\s*(?:here(?:'s| is) the (?:english )?translation"
        r"|translation below"
        r"|translated text"
        r"|sure!?[,.]?\s*here"
        r"|certainly!?[,.]?\s*here"
        r"|of course!?[,.]?\s*here"
        r")[:\s]*\n?)",
        re.IGNORECASE | re.MULTILINE,
    ),
]

_POSTSCRIPT_PATTERNS = [
    re.compile(
        r"(\n\s*\((?:note|notes?|n\.b\.|caveat|disclaimer)[^)]*\)\s*)$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"(\n\s*(?:hope this helps|let me know if).*)$",
        re.IGNORECASE,
    ),
]


# ── Code fence helpers ───────────────────────────────────────

_FENCE_OPEN = re.compile(r"^```[\w]*\s*$", re.MULTILINE)
_FENCE_CLOSE = re.compile(r"^```\s*$", re.MULTILINE)


def _balance_fences(text: str) -> str:
    opens = list(_FENCE_OPEN.finditer(text))
    open_starts = {m.start() for m in opens}
    closes = [m for m in _FENCE_CLOSE.finditer(text) if m.start() not in open_starts]

    n_opens = len(opens)
    n_closes = len(closes)

    if n_opens == n_closes:
        return text

    if n_opens == n_closes + 1:
        text = text.rstrip() + "\n```\n"
        logger.debug("Added missing closing code fence")
        return text

    if n_closes == n_opens + 1 and closes:
        last = closes[-1]
        text = text[: last.start()] + text[last.end() :]
        logger.debug("Removed extra closing code fence")
        return text

    logger.warning("Code fence mismatch (%d opens, %d closes); stripping all", n_opens, n_closes)
    text = _FENCE_OPEN.sub("", text)
    text = _FENCE_CLOSE.sub("", text)
    return text


# ── Table validation ─────────────────────────────────────────

_TABLE_ROW = re.compile(r"^\|.*\|$", re.MULTILINE)
_TABLE_SEP = re.compile(r"^\|[\s\-:]+\|", re.MULTILINE)


def _validate_tables(text: str) -> str:
    """
    Insert a missing separator row after a table header so
    marked.parse() renders it correctly.
    """
    rows = list(_TABLE_ROW.finditer(text))
    if len(rows) < 2:
        return text

    for row in rows:
        after = text[row.end() :]
        first_line = after.split("\n", 1)[0] if "\n" in after else after.strip()
        if _TABLE_SEP.match(first_line.strip()):
            continue
        cols = row.group().strip().strip("|").count("|") + 1
        sep = "|" + "|".join([" --- " for _ in range(cols)]) + "|"
        text = text[: row.end()] + "\n" + sep + text[row.end() :]
        logger.debug("Inserted table separator (%d cols)", cols)
        break

    return text


# ── Public API ───────────────────────────────────────────────

def sanitize_translation(text: str, *, original_ocr: str = "") -> str:
    """
    Clean up LLM translation output:
      1. Strip preamble / postscript commentary
      2. Balance code fences
      3. Validate / repair markdown tables
      4. Unicode NFKC normalisation
      5. Trim
    """
    if not text or not ENABLE_POST_TRANSLATION_SANITIZE:
        return text or ""

    for pat in _PREAMBLE_PATTERNS:
        text = pat.sub("", text, count=1)
    for pat in _POSTSCRIPT_PATTERNS:
        text = pat.sub("", text, count=1)

    text = _balance_fences(text)
    text = _validate_tables(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.strip()

    logger.debug("Sanitized translation: %d→%d chars", len(original_ocr) if original_ocr else 0, len(text))
    return text