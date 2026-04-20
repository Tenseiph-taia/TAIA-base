import io
import re
import unicodedata
import logging
from typing import Tuple, List, Optional

import numpy as np
from PIL import Image

from .model import get_reader
from .config import (
    OCR_CONFIDENCE_THRESHOLD,
    ENABLE_UNICODE_NORMALIZE,
    STRIP_OCR_ARTIFACTS,
    JOIN_HYPHENATED_WORDS,
)
from .image import preprocess_image

logger = logging.getLogger("taia-ocr")


# ── Text Cleaning ────────────────────────────────────────────

_ARTIFACT_PATTERNS = [
    (re.compile(r"[─━]+"), ""),                    # stray horizontal rules
    (re.compile(r"[│┃┆┇┊┋]+"), ""),                # stray vertical rules
    (re.compile(r"^\s*[•‧]+(?=\s*$)", re.M), ""), # bullet-only lines
    (re.compile(r"\n{3,}"), "\n\n"),               # collapse blank lines
]

_HYPHEN_BREAK = re.compile(r"(\w)[-‐‑]\s*\n\s*(\w)")


def clean_ocr_text(
    raw: str,
    *,
    normalize: bool = True,
    strip_artifacts: bool = True,
    join_hyphenated: bool = True,
) -> str:
    """
    Clean raw OCR output before translation.
    1. Unicode NFKC normalisation
    2. Join mid-word hyphenated line breaks
    3. Strip common OCR artefacts
    4. Trim trailing whitespace per line
    """
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


# ── Text Reconstruction ──────────────────────────────────────


class TextBlock:
    """Represents one detected text block with position info."""

    __slots__ = ('x', 'y', 'w', 'h', 'text', 'confidence')

    def __init__(self, polygon, text: str, confidence: float):
        # polygon is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        self.x = min(xs)
        self.y = min(ys)
        self.w = max(xs) - self.x
        self.h = max(ys) - self.y
        self.text = text
        self.confidence = confidence


def _group_into_lines(blocks: List[TextBlock], y_tolerance: float = 0.5) -> List[List[TextBlock]]:
    """
    Group blocks into horizontal lines based on vertical overlap.

    y_tolerance: fraction of median block height. Blocks within this
    vertical distance are considered on the same line.
    """
    if not blocks:
        return []

    # Sort by vertical position
    sorted_blocks = sorted(blocks, key=lambda b: (b.y, b.x))

    # Calculate median height for tolerance
    heights = [b.h for b in sorted_blocks if b.h > 0]
    median_h = np.median(heights) if heights else 20
    tolerance = median_h * y_tolerance

    lines: List[List[TextBlock]] = []
    current_line: List[TextBlock] = [sorted_blocks[0]]

    for block in sorted_blocks[1:]:
        # Check if this block is on the same line as the last one
        prev = current_line[-1]
        vertical_diff = abs(block.y - prev.y)

        if vertical_diff <= tolerance:
            current_line.append(block)
        else:
            # Sort current line by horizontal position
            current_line.sort(key=lambda b: b.x)
            lines.append(current_line)
            current_line = [block]

    if current_line:
        current_line.sort(key=lambda b: b.x)
        lines.append(current_line)

    return lines


def _should_merge_blocks(left: TextBlock, right: TextBlock, median_h: float) -> bool:
    """
    Should two adjacent blocks on the same line be merged?
    They should be merged if the gap between them is small enough
    that they're likely part of the same word or phrase.
    """
    gap = right.x - (left.x + left.w)
    if gap < 0:
        return True  # Overlapping — definitely merge

    # If gap is less than 1/3 of median character width, merge
    # CJK characters are roughly square, so char_width ≈ height
    char_width = median_h * 0.6  # slightly less than square for mixed text
    return gap < char_width * 0.5


def _reconstruct_text(blocks: List[TextBlock]) -> str:
    """
    Reconstruct readable text from spatially-arranged blocks.

    Strategy:
    1. Group blocks into lines by vertical position
    2. Within each line, merge blocks that are close together
    3. Separate blocks that are far apart (likely different columns or paragraphs)
    4. Detect paragraph breaks by indentation changes
    """
    if not blocks:
        return ""

    heights = [b.h for b in blocks if b.h > 0]
    median_h = np.median(heights) if heights else 20

    lines = _group_into_lines(blocks)

    def is_aligned(row1, row2, tolerance=None):
        if tolerance is None:
            tolerance = max(30, median_h * 1.5)
        
        if abs(len(row1) - len(row2)) > 1:
            return False

        matches = 0
        for c1 in row1:
            for c2 in row2:
                if abs(c1[1] - c2[1]) < tolerance:
                    matches += 1
                    break

        return matches >= min(len(row1), len(row2)) - 1

    structured_lines = []

    for line_blocks in lines:
        if not line_blocks:
            continue

        # Sort left to right
        line_blocks.sort(key=lambda b: b.x)

        # Merge close blocks into segments (track bounding boxes for accurate gap calculation)
        segments = []
        current_text = line_blocks[0].text
        segment_start = line_blocks[0]
        segment_end = line_blocks[0]

        for i in range(1, len(line_blocks)):
            prev = line_blocks[i - 1]
            curr = line_blocks[i]

            if _should_merge_blocks(prev, curr, median_h):
                # Merge — no space between CJK, space between Latin
                prev_last_char = prev.text[-1] if prev.text else ''
                curr_first_char = curr.text[0] if curr.text else ''

                if _is_cjk(prev_last_char) or _is_cjk(curr_first_char):
                    current_text += curr.text
                else:
                    # Both Latin — add space only if there's a significant gap
                    gap = curr.x - (prev.x + prev.w)
                    char_width = median_h * 0.5
                    if gap > char_width * 0.3:
                        current_text += " " + curr.text
                    else:
                        current_text += curr.text
                segment_end = curr
            else:
                # Gap is too large — these are separate segments
                segments.append((current_text, segment_start, segment_end))
                current_text = curr.text
                segment_start = curr
                segment_end = curr

        segments.append((current_text, segment_start, segment_end))
        
        # Detect large gaps between segments (column separation)
        column_threshold = median_h * 4
        
        line_columns = []
        current_column_text, current_start, current_end = segments[0]
        
        for i in range(1, len(segments)):
            next_text, next_start, next_end = segments[i]
            
            gap = next_start.x - (current_end.x + current_end.w)
            
            if gap > column_threshold:
                # New column
                left = current_start.x
                right = current_end.x + current_end.w
                segment_center_x = (left + right) / 2
                
                line_columns.append((current_column_text, segment_center_x))
                
                current_column_text = next_text
                current_start = next_start
            else:
                # Same column
                if _is_cjk(current_column_text[-1] if current_column_text else ''):
                    current_column_text += next_text
                else:
                    current_column_text += " " + next_text
            
            current_end = next_end
        
        left = current_start.x
        right = current_end.x + current_end.w
        segment_center_x = (left + right) / 2
        line_columns.append((current_column_text, segment_center_x))
        
        structured_lines.append(line_columns)

    # Detect table groups by column alignment
    reconstructed_lines: List[str] = []

    if structured_lines:
        table_groups = []
        current_group = [structured_lines[0]]

        for i in range(1, len(structured_lines)):
            prev = structured_lines[i - 1]
            curr = structured_lines[i]

            if is_aligned(prev, curr):
                current_group.append(curr)
            else:
                table_groups.append(current_group)
                current_group = [curr]

        table_groups.append(current_group)

        # Render output
        for group in table_groups:
            if len(group) >= 2:
                # Table region: preserve column alignment
                for row in group:
                    row_text = "    ".join(col[0] for col in row)
                    reconstructed_lines.append(row_text)
            else:
                # Normal line
                row = group[0]
                row_text = " ".join(col[0] for col in row)
        reconstructed_lines.append(row_text)

    # --- Code block detection ---
    final_lines = []
    i = 0

    while i < len(reconstructed_lines):
        line = reconstructed_lines[i]

        if _is_code_line(line):
            code_block = [line]
            i += 1

            # Group consecutive code-like lines
            while (
                i < len(reconstructed_lines)
                and _is_code_line(reconstructed_lines[i])
                and reconstructed_lines[i].strip()  # avoid empty lines joining blocks
                and len(reconstructed_lines[i]) < 200  # avoid huge blocks from OCR errors
            ):
                code_block.append(reconstructed_lines[i])
                i += 1

            lang = _detect_code_language(code_block)
            
            if lang:
                final_lines.append(f"```{lang}\n" + "\n".join(code_block) + "\n```")
            else:
                final_lines.append("```\n" + "\n".join(code_block) + "\n```")
        else:
            final_lines.append(line)
            i += 1

    # --- List reconstruction ---
    normalized_lines = []
    i = 0

    while i < len(final_lines):
        line = final_lines[i]

        # Skip code blocks entirely
        if line.startswith("```"):
            normalized_lines.append(line)
            i += 1
            continue

        if _is_list_line(line):
            list_group = [_normalize_list_line(line)]
            i += 1

            # Group consecutive list items
            while i < len(final_lines) and _is_list_line(final_lines[i]):
                list_group.append(_normalize_list_line(final_lines[i]))
                i += 1

            normalized_lines.extend(list_group)
        else:
            normalized_lines.append(line)
            i += 1

    return "\n".join(normalized_lines)


_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3040, 0x309F),
    (0x30A0, 0x30FF),
    (0x3400, 0x4DBF),
    (0xFF00, 0xFFEF),
)


def _is_cjk(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _is_code_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    # Indentation is a strong signal
    if text.startswith(("    ", "\t")):
        return True

    # Strong signals
    if stripped.startswith(("def ", "class ", "return ", "if ", "for ", "while ")):
        return True

    if stripped.endswith(("{", "}", ";")):
        return True

    if "=" in stripped and any(op in stripped for op in ["==", "!=", "<=", ">="]):
        return True

    symbol_count = sum(1 for c in stripped if c in "{}[]();=<>+-*/_%")

    has_cjk = any(
        '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff'
        for c in stripped
    )

    if "(" in stripped and ")" in stripped and symbol_count >= 2:
        return True

    if symbol_count >= 4 and not has_cjk:
        return True

    return False


def _detect_code_language(lines: List[str]) -> str:
    text = "\n".join(lines).lower()

    # Python signals
    if any(keyword in text for keyword in ["def ", "import ", "print(", "self", "none"]):
        return "python"

    # Strong SQL detection
    if (
        "select " in text and " from " in text
    ) or any(keyword in text for keyword in [
        "insert into ", "update ", "delete from ", "join ", "group by ", "order by "
    ]):
        return "sql"

    # JavaScript signals
    if any(keyword in text for keyword in ["function ", "console.log", "var ", "let ", "const "]):
        return "javascript"

    # Bash / shell
    if any(keyword in text for keyword in ["#!/bin/bash", "echo ", "cd ", "ls ", "grep "]):
        return "bash"

    # Indentation hint (great for Python OCR)
    if any(line.startswith(("    ", "\t")) for line in lines):
        return "python"

    return ""


def _is_list_line(text: str) -> bool:
    stripped = text.strip()

    if not stripped:
        return False

    # Bullet symbols
    if stripped.startswith(("•", "●", "○", "-", "–", "—", "*")):
        return True

    # Numbered list (1.  2.1  etc)
    if re.match(r'^\d+(\.\d+)*[\.\)]\s', stripped):
        return True

    return False


def _normalize_list_line(text: str) -> str:
    stripped = text.strip()

    # Replace bullet variants with "-"
    if stripped.startswith(("•", "●", "○", "*", "–", "—")):
        return "- " + stripped[1:].strip()

    return stripped


def _join_lines_with_paragraphs(
    lines: List[str],
    blocks: List[TextBlock],
    median_h: float,
) -> str:
    """
    Join lines into paragraphs. A paragraph break is detected when:
    - There's a large vertical gap (more than 1.5x line height)
    - The next line is indented significantly
    - The previous line doesn't end with a sentence-ending character
    """
    if len(lines) <= 1:
        return "\n".join(lines)

    # Re-group blocks by line to get y positions
    line_groups = _group_into_lines(blocks)
    if len(line_groups) != len(lines):
        # Fallback: just join with newlines
        return "\n".join(lines)

    result_parts: List[str] = [lines[0]]

    for i in range(1, len(lines)):
        prev_group = line_groups[i - 1]
        curr_group = line_groups[i]

        # Calculate vertical gap
        prev_bottom = max(b.y + b.h for b in prev_group)
        curr_top = min(b.y for b in curr_group)
        vertical_gap = curr_top - prev_bottom

        # Calculate horizontal indentation
        prev_left = min(b.x for b in prev_group)
        curr_left = min(b.x for b in curr_group)
        indent = curr_left - prev_left

        # Paragraph break conditions
        large_gap = vertical_gap > median_h * 1.5
        significant_indent = indent > median_h * 2 and indent > 20

        if large_gap or significant_indent:
            result_parts.append("\n\n" + lines[i])
        else:
            # Same paragraph — for CJK text, no space between lines
            prev_text = lines[i - 1]
            if prev_text and _is_cjk(prev_text[-1]):
                result_parts.append(lines[i])
            else:
                # Mixed or Latin — join with space
                result_parts.append(" " + lines[i])

    return "".join(result_parts)


# ── Sorting ──────────────────────────────────────────────────

def _sort_key(polygon):
    """Sort by vertical then horizontal position (10px line tolerance)."""
    y = polygon[0][1]
    x = polygon[0][0]
    return (round(y / 10), x)


# ── Multi-strategy OCR ──────────────────────────────────────

def _ocr_with_preprocessing(img_bytes: bytes, reader) -> Tuple[str, float]:
    """OCR with preprocessing applied. Returns (text, avg_confidence)."""
    processed = preprocess_image(img_bytes)
    img = Image.open(io.BytesIO(processed)).convert("RGB")
    img_np = np.array(img)
    result = reader.ocr(img_np, cls=True)

    if not result or result[0] is None:
        return ("", 0.0)

    return _extract_from_result(result)


def _ocr_without_preprocessing(img_bytes: bytes, reader) -> Tuple[str, float]:
    """OCR on the raw image without preprocessing. Returns (text, avg_confidence)."""
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)
        result = reader.ocr(img_np, cls=True)

        if not result or result[0] is None:
            return ("", 0.0)

        return _extract_from_result(result)
    except Exception:
        return ("", 0.0)


def _extract_from_result(result) -> Tuple[str, float]:
    """
    Extract text from PaddleOCR result using spatial reconstruction.
    Returns (reconstructed_text, avg_confidence).
    """
    lines_data = result[0]
    if not lines_data:
        return ("", 0.0)

    blocks: List[TextBlock] = []
    total_conf = 0.0
    accepted = 0

    for line in lines_data:
        try:
            polygon, (text, score) = line[0], line[1]
            if score >= OCR_CONFIDENCE_THRESHOLD:
                blocks.append(TextBlock(polygon, text, score))
                total_conf += score
                accepted += 1
        except Exception:
            continue

    if not blocks:
        return ("", 0.0)

    avg_conf = total_conf / accepted

    # Use spatial reconstruction instead of simple sort+join
    reconstructed = _reconstruct_text(blocks)

    return (reconstructed, avg_conf)


def ocr_image_bytes_with_conf(img_bytes: bytes) -> Tuple[str, float]:
    """
    OCR a single image with multi-strategy approach.

    Strategy:
    1. Try with preprocessing
    2. Try without preprocessing
    3. Pick the result with higher average confidence

    Returns (cleaned_text, avg_confidence).
    """
    try:
        reader = get_reader()

        # Strategy 1: With preprocessing
        text_pp, conf_pp = _ocr_with_preprocessing(img_bytes, reader)

        # If confidence is high enough, use it directly
        if conf_pp >= 0.85 and len(text_pp) > 10:
            cleaned = clean_ocr_text(
                text_pp,
                normalize=ENABLE_UNICODE_NORMALIZE,
                strip_artifacts=STRIP_OCR_ARTIFACTS,
                join_hyphenated=JOIN_HYPHENATED_WORDS,
            )
            logger.debug("OCR (preprocessed): conf=%.2f, %d chars", conf_pp, len(cleaned))
            return (cleaned, conf_pp)

        # Strategy 2: Without preprocessing (raw image)
        text_raw, conf_raw = _ocr_without_preprocessing(img_bytes, reader)

        # Pick the better result
        if conf_raw > conf_pp and len(text_raw) > 0:
            logger.debug(
                "OCR: raw better (conf %.2f > %.2f), using raw result",
                conf_raw, conf_pp,
            )
            best_text, best_conf = text_raw, conf_raw
        elif len(text_pp) > 0:
            best_text, best_conf = text_pp, conf_pp
        elif len(text_raw) > 0:
            best_text, best_conf = text_raw, conf_raw
        else:
            return ("", 0.0)

        cleaned = clean_ocr_text(
            best_text,
            normalize=ENABLE_UNICODE_NORMALIZE,
            strip_artifacts=STRIP_OCR_ARTIFACTS,
            join_hyphenated=JOIN_HYPHENATED_WORDS,
        )

        logger.debug("OCR: conf=%.2f, %d chars", best_conf, len(cleaned))
        return (cleaned, best_conf)

    except Exception:
        logger.error("OCR extraction failed", exc_info=True)
        return ("", 0.0)


def ocr_image_bytes(img_bytes: bytes) -> str:
    """OCR a single image. Returns extracted text. (backward compatible)"""
    text, _ = ocr_image_bytes_with_conf(img_bytes)
    return text


def process_ocr_result(ocr_result):
    """
    Process external OCR result.
    For now, fallback to string conversion.
    Layout reconstruction is handled internally by PaddleOCR pipeline.
    """
    if isinstance(ocr_result, str):
        return clean_ocr_text(ocr_result)

    # Fallback: convert to string safely
    if isinstance(ocr_result, (list, dict)):
        return ""

    return clean_ocr_text(str(ocr_result))


def ocr_pages_batch(page_images: list[tuple[bytes, int, int]]) -> list[str]:
    """
    OCR multiple page images sequentially (PaddleOCR is not thread-safe).
    Args: page_images = list of (image_bytes, width, height)
    Returns: list of markdown strings, one per page
    """
    results = []
    for img_bytes, w, h in page_images:
        text = ocr_image_bytes(img_bytes)
        results.append(text)
    return results


def get_image_info(img_bytes: bytes) -> tuple[int, int]:
    """Get width and height of an image."""
    try:
        img = Image.open(io.BytesIO(img_bytes))
        return img.size
    except Exception:
        return (0, 0)