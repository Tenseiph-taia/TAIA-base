"""
OCR Text Reflow Module
Reconstructs fragmented OCR lines into coherent paragraphs for better translation quality.
"""
import re
from typing import List, Set

# Japanese punctuation that indicates end of sentence
SENTENCE_ENDERS: Set[str] = {'。', '．', '.', '!', '?'}

# Common SQL keywords (uppercase) to identify headers/code
SQL_KEYWORDS: Set[str] = {
    'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL',
    'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'TABLE',
    'INDEX', 'GROUP', 'ORDER', 'BY', 'HAVING', 'LIMIT', 'OFFSET', 'UNION',
    'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN', 'IS', 'NULL', 'AS',
    'ON', 'USING', 'VALUES', 'SET', 'INTO', 'DATABASE', 'SCHEMA'
}

def _is_heading_line(line: str) -> bool:
    """Check if line is a heading, code, or should be preserved as-is."""
    stripped = line.strip()
    
    # Empty lines are not headings
    if not stripped:
        return False
    
    # Line is all uppercase (likely heading or code)
    if stripped.isupper():
        return True
    
    # Line starts with number followed by period (e.g. "1. ", "2.1 ")
    if re.match(r'^\d+(\.\d+)*\s', stripped):
        return True
    
    # Line contains ONLY SQL keywords
    words = stripped.split()
    if words and all(word.upper() in SQL_KEYWORDS for word in words if word.isalpha()):
        return True
    
    return False

def reflow_japanese_text(text: str) -> str:
    """
    Reconstruct fragmented OCR Japanese text into coherent paragraphs.
    
    Merges broken lines that do not end with sentence-ending punctuation.
    Preserves headings, numbered lists, and code lines.
    Removes empty lines.
    
    Args:
        text: Raw fragmented OCR text
        
    Returns:
        Clean text with proper paragraph structure
    """
    if not text:
        return ""
    
    lines = text.splitlines()
    processed: List[str] = []
    current_paragraph: List[str] = []
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            if current_paragraph:
                processed.append('\n'.join(current_paragraph))
                current_paragraph = []
            continue
        
        # Check if this line should be preserved as-is
        if _is_heading_line(stripped):
            # Finalize current paragraph if exists
            if current_paragraph:
                processed.append('\n'.join(current_paragraph))
                current_paragraph = []
            processed.append(stripped)
            continue
        
        # Preserve very short non-Japanese lines (likely labels, bullets, or structure)
        if len(stripped) < 3 and not any(
            '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff'
            for c in stripped
        ):
            if current_paragraph:
                processed.append('\n'.join(current_paragraph))
                current_paragraph = []
            processed.append(stripped)
            continue
        
        # Add line to current paragraph
        current_paragraph.append(stripped)
        
        # Check if this line ends with sentence punctuation OR we have enough lines
        last_char = stripped[-1]
        if last_char in SENTENCE_ENDERS or len(current_paragraph) >= 3:
            processed.append('\n'.join(current_paragraph))
            current_paragraph = []
    
    # Add any remaining text in current paragraph
    if current_paragraph:
        processed.append('\n'.join(current_paragraph))
    
    # Join with proper line breaks between paragraphs
    return '\n\n'.join(processed)