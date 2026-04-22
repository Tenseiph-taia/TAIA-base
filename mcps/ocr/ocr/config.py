import os

# ── Document Limits ────────────────────────────────────────────
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_IMAGES_PER_DOC = 500
OCR_MIN_CHAR_COUNT = int(os.getenv("OCR_MIN_CHAR_COUNT", "1"))
OCR_MIN_CJK_RATIO = float(os.getenv("OCR_MIN_CJK_RATIO", "0.3"))

# ── PDF Rendering ──────────────────────────────────────────────
PDF_RENDER_DPI = int(os.getenv("OCR_PDF_DPI", "300"))

# ── Rate Limiting ──────────────────────────────────────────────
RATE_LIMIT_REQUESTS = int(os.getenv("OCR_RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW   = float(os.getenv("OCR_RATE_LIMIT_WINDOW", "1.0"))

# ── VLM OCR Backend ────────────────────────────────────────────
# Both Ollama and vLLM expose the OpenAI-compatible
# /v1/chat/completions endpoint — the client code is identical.
# Switch backends purely by changing VLM_URL and VLM_BACKEND.
VLM_BACKEND          = os.getenv("VLM_BACKEND", "ollama")          # ollama | vllm
VLM_URL              = os.getenv("VLM_URL",     "http://ollama:11434")
VLM_MODEL            = os.getenv("VLM_MODEL",   "qwen3-vl:4b")
VLM_TIMEOUT          = float(os.getenv("VLM_TIMEOUT",     "900.0"))
VLM_MAX_TOKENS       = int(os.getenv("VLM_MAX_TOKENS",    "4096"))
# Pages processed concurrently. Keep 1 for single-GPU Ollama;
# raise for multi-GPU vLLM deployments.
VLM_OCR_CONCURRENCY  = int(os.getenv("VLM_OCR_CONCURRENCY", "1"))

# ── Translation ────────────────────────────────────────────────
TRANSLATION_API_URL  = os.getenv("TRANSLATION_API_URL", "")
TRANSLATION_API_KEY  = os.getenv("TRANSLATION_API_KEY", "")
TRANSLATION_MODEL    = os.getenv("TRANSLATION_MODEL",   "")
TRANSLATION_ENABLED  = bool(TRANSLATION_API_URL and TRANSLATION_MODEL)
REQUIRE_JAPANESE_DETECTION = os.getenv("OCR_REQUIRE_JAPANESE_DETECTION", "1") == "1"

# ── Storage ────────────────────────────────────────────────────
UPLOAD_DIR              = os.getenv("OCR_UPLOAD_DIR",              "uploads")
DOCUMENT_CLEANUP_HOURS  = int(os.getenv("OCR_DOCUMENT_CLEANUP_HOURS", "24"))

# ── Service URLs ───────────────────────────────────────────────
VIEWER_BASE_URL = os.getenv("VIEWER_BASE_URL", "http://localhost:8004")
API_BASE_URL    = os.getenv("API_BASE_URL",    "http://localhost:8004")

# ── Text Post-Processing ───────────────────────────────────────
# Applied to VLM output as a light cleanup pass only.
# Does NOT alter markdown structure.
ENABLE_UNICODE_NORMALIZE = os.getenv("OCR_ENABLE_UNICODE_NORMALIZE", "1") == "1"
STRIP_OCR_ARTIFACTS      = os.getenv("OCR_STRIP_ARTIFACTS",          "1") == "1"
JOIN_HYPHENATED_WORDS    = os.getenv("OCR_JOIN_HYPHENATED_WORDS",     "1") == "1"

# ── Translation Post-Processing ────────────────────────────────
ENABLE_POST_TRANSLATION_SANITIZE = os.getenv("OCR_ENABLE_POST_TRANSLATION_SANITIZE", "1") == "1"
