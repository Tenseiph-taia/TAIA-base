import base64
import binascii
import re
from PIL import Image
from .config import MAX_FILE_SIZE

Image.MAX_IMAGE_PIXELS = 50_000_000


def safe_base64_decode(data: str) -> bytes:
    data = data.strip()
    if len(data) > MAX_FILE_SIZE * 1.4:
        raise ValueError("Input too large")
    try:
        return base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError):
        pass
    cleaned = re.sub(r'[^A-Za-z0-9+/=_-]', '', data)
    cleaned = cleaned.replace('-', '+').replace('_', '/')
    cleaned += '=' * (-len(cleaned) % 4)
    try:
        return base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError):
        pass
    remainder = len(cleaned.rstrip('=')) % 4
    if remainder == 1:
        cleaned = cleaned.rstrip('=')[:-1]
        cleaned += '=' * (-len(cleaned) % 4)
    return base64.b64decode(cleaned, validate=False)


def parse_data_url(data_url: str):
    match = re.match(r"data:([^;]+);base64,(.+)", data_url, re.DOTALL)
    if match:
        mime = match.group(1)
        data = safe_base64_decode(match.group(2))
        ext_map = {
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }
        return data, ext_map.get(mime, ".bin")
    return safe_base64_decode(data_url), ".bin"