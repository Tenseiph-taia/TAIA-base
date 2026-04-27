"""
config.py — Runtime configuration for taia-browser-harness.

All values are read from environment variables at import time.
Defaults are safe for production use inside Docker Compose.
No external dependencies — stdlib only.
"""

import os


def _int(key: str, default: int) -> int:
    raw = os.environ.get(key, "")
    try:
        return int(raw)
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


def _str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _float(key: str, default: float) -> float:
    raw = os.environ.get(key, "")
    try:
        return float(raw)
    except ValueError:
        return default


# ── Browser launch ────────────────────────────────────────────────────────

# Run Chromium without a visible window (required inside Docker)
BROWSER_HEADLESS: bool = _bool("BROWSER_HEADLESS", True)

# Viewport dimensions for every new page
BROWSER_VIEWPORT_WIDTH: int = _int("BROWSER_VIEWPORT_WIDTH", 1280)
BROWSER_VIEWPORT_HEIGHT: int = _int("BROWSER_VIEWPORT_HEIGHT", 900)

# ── Timeouts ─────────────────────────────────────────────────────────────

# Default timeout for element interactions (ms)
BROWSER_DEFAULT_TIMEOUT_MS: int = _int("BROWSER_DEFAULT_TIMEOUT_MS", 10_000)

# Timeout for full page navigations (ms)
BROWSER_NAVIGATION_TIMEOUT_MS: int = _int("BROWSER_NAVIGATION_TIMEOUT_MS", 30_000)

# ── Session management ────────────────────────────────────────────────────

# Minutes of inactivity before a session is automatically closed
BROWSER_SESSION_TIMEOUT_MINUTES: int = _int("BROWSER_SESSION_TIMEOUT_MINUTES", 30)

# Hard cap on simultaneously open sessions
BROWSER_MAX_SESSIONS: int = _int("BROWSER_MAX_SESSIONS", 50)

# Optional proxy for outbound traffic (e.g. http://proxy:8080)
BROWSER_PROXY: str = _str("BROWSER_PROXY", "")

# ── Screenshots ───────────────────────────────────────────────────────────

# Screenshots are downscaled to this width (px) before base64 encoding.
# Height is scaled proportionally. Set to 0 to disable resizing.
BROWSER_SCREENSHOT_MAX_WIDTH: int = _int("BROWSER_SCREENSHOT_MAX_WIDTH", 1280)

# ── Live viewport ─────────────────────────────────────────────────────────
BROWSER_LATEST_SCREENSHOT_PATH: str = _str("BROWSER_LATEST_SCREENSHOT_PATH", "")

# ── Rate limiting ──────────────────────────────────────────────────────────
# Maximum requests per connection (token bucket capacity)
BROWSER_RATE_LIMIT_MAX: int = _int("BROWSER_RATE_LIMIT_MAX", 100)
# Token refill rate per second
BROWSER_RATE_LIMIT_REFILL: float = _float("BROWSER_RATE_LIMIT_REFILL", 10.0)
# Burst limit - max requests per window
BROWSER_BURST_LIMIT_MAX: int = _int("BROWSER_BURST_LIMIT_MAX", 20)
# Burst window in seconds
BROWSER_BURST_LIMIT_WINDOW: int = _int("BROWSER_BURST_LIMIT_WINDOW", 60)

# ── Security ───────────────────────────────────────────────────────────────
# Allow specific origins for CORS (comma-separated)
# Leave empty for all origins (not recommended for production)
BROWSER_CORS_ALLOWED_ORIGINS: str = _str("BROWSER_CORS_ALLOWED_ORIGINS", "")
