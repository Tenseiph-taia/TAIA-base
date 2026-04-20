import os

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_IMAGES_PER_DOC = 500
OCR_CONFIDENCE_THRESHOLD = 0.5

ENABLE_PREPROCESSING = os.getenv("OCR_ENABLE_PREPROCESSING", "1") == "1"

# PaddleOCR is NOT thread-safe. Must be 1.
OCR_CONCURRENCY = 1

# PDF render quality
PDF_RENDER_DPI = int(os.getenv("OCR_PDF_DPI", "300"))

# Rate limiting
RATE_LIMIT_REQUESTS = int(os.getenv("OCR_RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW = float(os.getenv("OCR_RATE_LIMIT_WINDOW", "1.0"))

# Translation — OpenAI-compatible endpoint (Ollama, vLLM, OpenAI, etc.)
TRANSLATION_API_URL = os.getenv("TRANSLATION_API_URL", "")
TRANSLATION_API_KEY = os.getenv("TRANSLATION_API_KEY", "")
TRANSLATION_MODEL = os.getenv("TRANSLATION_MODEL", "")
TRANSLATION_ENABLED = bool(TRANSLATION_API_URL and TRANSLATION_MODEL)

# Storage
UPLOAD_DIR = os.getenv("OCR_UPLOAD_DIR", "uploads")
DOCUMENT_CLEANUP_HOURS = int(os.getenv("OCR_DOCUMENT_CLEANUP_HOURS", "24"))

# Viewer URL — must be reachable from the user's browser
VIEWER_BASE_URL = os.getenv("VIEWER_BASE_URL", "http://localhost:8004")

# Internal API URL — used by MCP server to call the API
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8004")

# ── Text Cleaning ──────────────────────────────────────────────
ENABLE_UNICODE_NORMALIZE = os.getenv("OCR_ENABLE_UNICODE_NORMALIZE", "1") == "1"
STRIP_OCR_ARTIFACTS = os.getenv("OCR_STRIP_ARTIFACTS", "1") == "1"
JOIN_HYPHENATED_WORDS = os.getenv("OCR_JOIN_HYPHENATED_WORDS", "1") == "1"

# ── Validation ────────────────────────────────────────────────
OCR_MIN_CHAR_COUNT = int(os.getenv("OCR_MIN_CHAR_COUNT", "3"))
OCR_MIN_CJK_RATIO = float(os.getenv("OCR_MIN_CJK_RATIO", "0.05"))
REQUIRE_JAPANESE_DETECTION = os.getenv("OCR_REQUIRE_JAPANESE_DETECTION", "1") == "1"

# ── Post-Translation Sanitization ─────────────────────────────
ENABLE_POST_TRANSLATION_SANITIZE = os.getenv("OCR_ENABLE_POST_TRANSLATION_SANITIZE", "1") == "1"

# ── Preprocessing Strategy ──────────────────────────────────
# Controls the multi-strategy OCR approach
OCR_MULTI_STRATEGY = os.getenv("OCR_MULTI_STRATEGY", "1") == "1"
OCR_HIGH_CONFIDENCE_THRESHOLD = float(os.getenv("OCR_HIGH_CONFIDENCE_THRESHOLD", "0.85"))
OCR_UPSCALE_SMALL_IMAGES = os.getenv("OCR_UPSCALE_SMALL_IMAGES", "1") == "1"
OCR_UPSCALE_MIN_DIMENSION = int(os.getenv("OCR_UPSCALE_MIN_DIMENSION", "1000"))