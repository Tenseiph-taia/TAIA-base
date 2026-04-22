import io
import re
import zipfile
from .core import ocr_image_bytes, get_image_info


def extract_docx_images(data: bytes) -> list[dict]:
    """
    Extract images from a DOCX file (treated as ZIP).
    Returns list of {"image": bytes, "width": int, "height": int}
    """
    images = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            media_files = [
                f for f in z.namelist()
                if f.startswith("word/media/") and not f.endswith(".xml")
            ]

            def sort_key(name):
                match = re.search(r'(\d+)', name.split("/")[-1])
                return int(match.group(1)) if match else 0

            media_files.sort(key=sort_key)

            for fname in media_files:
                img_data = z.read(fname)
                if len(img_data) < 100:
                    continue
                w, h = get_image_info(img_data)
                images.append({"image": img_data, "width": w, "height": h})
    except Exception:
        pass

    return images