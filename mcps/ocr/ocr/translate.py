"""
Server-side translation using any OpenAI-compatible API endpoint.
Called by the background task after each page is OCR'd.
Works with Ollama, vLLM, OpenAI, etc.
"""
import httpx
import logging
from dataclasses import dataclass
from typing import Optional

from .config import (
    TRANSLATION_API_URL,
    TRANSLATION_API_KEY,
    TRANSLATION_MODEL,
    TRANSLATION_ENABLED,
    ENABLE_POST_TRANSLATION_SANITIZE,
)
from .validators import validate_ocr_output, ValidationResult
from .sanitizer import sanitize_translation

logger = logging.getLogger("taia-ocr")

SYSTEM_PROMPT = """You are a professional Japanese-to-English technical translator specialising in software engineering, database administration, and system architecture documents.

Rules — follow them strictly:
1. Translate ALL Japanese text into natural, accurate English.
2. Preserve ALL markdown formatting exactly: headings (#, ##, ###), bullet lists (-, *), numbered lists, bold (**text**), italic (*text*), and links [text](url).
3. Preserve ALL code blocks (``` … ```) and inline code (`…`) exactly as-is. Do NOT translate code, variable names, or comments inside code blocks.
4. Preserve table structure (| col | col |) and alignment separator rows (| --- | --- |).
5. Keep technical terms accurate: Pro*C, SQL, Oracle, DB2, PL/SQL, COBOL, shell, AWK, sed, etc. Do not paraphrase them.
6. Output ONLY the English translation. No commentary, notes, explanations, or preamble. No "Here is the translation:" or similar.
7. If a line contains no Japanese (e.g. it is already English or is pure code), reproduce it unchanged."""


@dataclass
class TranslationResult:
    """Structured output from the translation step."""
    translated_text: str
    original_ocr_text: str
    validation: ValidationResult
    translation_failed: bool = False
    error_message: str = ""


async def _call_api(text: str) -> str:
    """
    Send text to the translation API. Returns raw response content.
    Raises on errors so caller can handle fallback.
    """
    headers = {"Content-Type": "application/json"}
    if TRANSLATION_API_KEY:
        headers["Authorization"] = f"Bearer {TRANSLATION_API_KEY}"

    base_url = TRANSLATION_API_URL.rstrip("/")
    if base_url.endswith("/chat/completions"):
        url = base_url
    elif base_url.endswith("/v1"):
        url = f"{base_url}/chat/completions"
    else:
        url = f"{base_url}/v1/chat/completions"

    logger.debug("Translation API call: %d chars input", len(text))

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            url,
            headers=headers,
            json={
                "model": TRANSLATION_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.3,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        data = response.json()

    if "choices" in data and data["choices"]:
        content = data["choices"][0]["message"]["content"]
        logger.debug("Translation API response: %d chars", len(content))
        return content

    logger.error("Unexpected translation response format: %s", list(data.keys()))
    raise ValueError(f"Unexpected response format: {list(data.keys())}")


async def translate_page_full(japanese_text: str) -> TranslationResult:
    """
    Full translation pipeline with validation and sanitization.

    1. Validate OCR output (skip translation if invalid)
    2. Call translation API
    3. Sanitize translation output
    4. Return structured result with fallback on failure
    """
    if not TRANSLATION_ENABLED:
        return TranslationResult(
            translated_text="",
            original_ocr_text=japanese_text,
            validation=ValidationResult(False, "Translation disabled"),
            translation_failed=True,
            error_message="Translation disabled",
        )

    if not japanese_text or not japanese_text.strip():
        return TranslationResult(
            translated_text="",
            original_ocr_text=japanese_text or "",
            validation=ValidationResult(False, "Empty input"),
            translation_failed=True,
            error_message="Empty input",
        )

    # 1. Validate
    validation = validate_ocr_output(japanese_text)
    logger.info(
        "OCR validation: valid=%s reason=%s is_japanese=%s",
        validation.is_valid, validation.reason, validation.is_japanese,
    )

    if not validation.is_valid:
        logger.warning("Skipping translation — %s", validation.reason)
        return TranslationResult(
            translated_text="",
            original_ocr_text=japanese_text,
            validation=validation,
            translation_failed=True,
            error_message=f"Validation failed: {validation.reason}",
        )

    # 2. Reflow fragmented OCR text before translation
    from ocr.reflow import reflow_japanese_text
    reflowed = reflow_japanese_text(japanese_text.strip())

    logger.debug(f"[REFLOW INPUT]\n{japanese_text[:500]}")
    logger.debug(f"[REFLOW OUTPUT]\n{reflowed[:500]}")

    japanese_text = reflowed

    # 2. Translate
    try:
        raw_translation = await _call_api(japanese_text)
    except httpx.TimeoutException:
        logger.error("Translation request timed out")
        return TranslationResult(
            translated_text="",
            original_ocr_text=japanese_text,
            validation=validation,
            translation_failed=True,
            error_message="Translation request timed out",
        )
    except httpx.HTTPStatusError as e:
        logger.error("Translation HTTP error: %s", e.response.status_code)
        return TranslationResult(
            translated_text="",
            original_ocr_text=japanese_text,
            validation=validation,
            translation_failed=True,
            error_message=f"HTTP {e.response.status_code}",
        )
    except Exception as e:
        logger.error("Translation failed: %s", e)
        return TranslationResult(
            translated_text="",
            original_ocr_text=japanese_text,
            validation=validation,
            translation_failed=True,
            error_message=str(e),
        )

    # 3. Sanitize
    if ENABLE_POST_TRANSLATION_SANITIZE:
        cleaned = sanitize_translation(raw_translation, original_ocr=japanese_text)
    else:
        cleaned = raw_translation.strip() if raw_translation else ""

    if not cleaned and raw_translation:
        logger.warning("Sanitization emptied result; using raw output")
        cleaned = raw_translation.strip()

    logger.info("Translation complete: %d OCR chars → %d translated chars", len(japanese_text), len(cleaned))

    return TranslationResult(
        translated_text=cleaned,
        original_ocr_text=japanese_text,
        validation=validation,
        translation_failed=False,
    )


async def translate_page(japanese_text: str) -> str:
    """
    Translate a single page of Japanese text to English.
    Backward-compatible wrapper — returns empty string on failure.

    NOTE: Callers that need failure metadata or OCR fallback should
    use translate_page_full() instead.
    """
    result = await translate_page_full(japanese_text)
    return result.translated_text