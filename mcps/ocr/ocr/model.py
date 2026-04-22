"""
Shared HTTP client for the VLM OCR backend.
Thread-safe singleton — safe to call from any thread or asyncio.to_thread().
"""

import threading
import logging
import httpx

from .config import VLM_URL, VLM_TIMEOUT

logger = logging.getLogger("taia-ocr")

_client: httpx.Client | None = None
_lock = threading.Lock()


def get_client() -> httpx.Client:
    """Return the shared httpx.Client for VLM requests."""
    global _client
    if _client is not None:
        return _client

    with _lock:
        if _client is not None:
            return _client

        logger.info("[VLM] Initialising HTTP client → %s", VLM_URL)
        # Use a generous read timeout — 8B VLM models can take
        # 3-5 min on first inference after VRAM load.
        # connect timeout stays short to catch network issues fast.
        _client = httpx.Client(
            base_url=VLM_URL,
            timeout=httpx.Timeout(
                timeout=VLM_TIMEOUT,   # total / read timeout
                connect=10.0,          # fail fast on network errors
            ),
            headers={"Content-Type": "application/json"},
        )
        logger.info("[VLM] Client ready.")
        return _client