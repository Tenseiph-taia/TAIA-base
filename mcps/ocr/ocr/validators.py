"""
Validation gate between OCR and translation.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .config import (
    OCR_MIN_CHAR_COUNT,
    OCR_MIN_CJK_RATIO,
    REQUIRE_JAPANESE_DETECTION,
)

logger = logging.getLogger("taia-ocr")


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str
    is_japanese: Optional[bool] = None


_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3040, 0x309F),
    (0x30A0, 0x30FF),
    (0x3400, 0x4DBF),
    (0xFF00, 0xFFEF),
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def cjk_ratio(text: str) -> float:
    """Proportion of CJK characters in text."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    return cjk / len(text)


def has_any_cjk(text: str) -> bool:
    """Returns True if text contains at least one CJK character."""
    return any(_is_cjk(ch) for ch in text)


def _detect_language(text: str) -> Optional[str]:
    try:
        from langdetect import detect
        return detect(text)
    except ImportError:
        return None
    except Exception:
        return None


def validate_ocr_output(text: str) -> ValidationResult:
    """
    Decide whether OCR output is good enough for translation.

    For technical documents (mixed Japanese + English + code), we use
    a softer check: if ANY CJK characters are present and the text is
    long enough, it's valid. Pure CJK ratio check is only used as a
    tiebreaker when langdetect is unavailable.
    """
    if not text or not text.strip():
        return ValidationResult(False, "OCR output is empty", False)

    stripped = text.strip()
    char_count = len(stripped)

    if char_count < OCR_MIN_CHAR_COUNT:
        return ValidationResult(
            False,
            f"OCR output too short ({char_count} < {OCR_MIN_CHAR_COUNT})",
            False,
        )

    contains_cjk = has_any_cjk(stripped)

    # If there are CJK characters, it's likely Japanese (or Chinese)
    # For technical docs, even a small amount of CJK is valid
    if not contains_cjk:
        return ValidationResult(
            False,
            "No CJK characters found — not Japanese text",
            False,
        )

    is_japanese: Optional[bool] = None

    if REQUIRE_JAPANESE_DETECTION:
        detected = _detect_language(stripped)
        if detected is not None:
            # Accept Japanese or Chinese (both get translated)
            is_japanese = detected in ("ja", "zh-cn", "zh-tw", "ko")
            if not is_japanese:
                # Still allow it if it has CJK — langdetect can be wrong on short texts
                ratio = cjk_ratio(stripped)
                if ratio >= OCR_MIN_CJK_RATIO:
                    logger.debug(
                        "langdetect said '%s' but CJK ratio %.2f — allowing",
                        detected, ratio,
                    )
                    is_japanese = True
                else:
                    return ValidationResult(
                        False,
                        f"Detected language '{detected}' with low CJK ratio",
                        False,
                    )
        else:
            is_japanese = True  # Has CJK chars, langdetect unavailable
    else:
        is_japanese = True  # Has CJK chars

    return ValidationResult(True, "OK", is_japanese)