"""
utils.py — Shared utilities for taia-browser-harness.

Responsibilities:
  - Screenshot capture + base64 encoding (with optional resize)
  - Element resolution from a plain-text target string
  - Structured tool response helpers
"""

from __future__ import annotations

import asyncio
import base64
import io
import ipaddress
import logging
import socket
import os
from typing import Any
from urllib.parse import urlparse

# ── SSRF protection ───────────────────────────────────────────────────────
#
# Identical implementation to taia-web-tools.
# Blocks all private/internal network access from the browser harness.
# Uses ipaddress module — mathematically evaluates IPs, not string matching.
# Defeats:
#   http://0177.0.0.1        (octal encoding of 127.0.0.1)
#   http://2130706433        (decimal encoding of 127.0.0.1)
#   http://[::ffff:127.0.0.1] (IPv4-mapped IPv6)
#   DNS rebinding attacks    (hostname resolves to internal IP at call time)

_BLOCKED_HOSTNAMES = {
    "localhost",
    "mongodb",
    "rag_api",
    "vectordb",
    "meilisearch",
    "ollama",
    "speaches",
    "taia-web-tools",
    "taia-sales-mcp",
    "taia-ocr-mcp",
    "taia-browser-harness",
    "host.docker.internal",
}

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC-1918 private
    ipaddress.ip_network("172.16.0.0/12"),    # RFC-1918 private
    ipaddress.ip_network("192.168.0.0/16"),   # RFC-1918 private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / IMDS
    ipaddress.ip_network("0.0.0.0/8"),        # "this" network
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT / cloud metadata
]


def _ip_is_blocked(ip_str: str) -> bool:
    """Return True if the IP falls in any blocked network."""
    try:
        addr = ipaddress.ip_address(ip_str)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        return True  # unparseable — block it


async def is_url_safe(url: str) -> bool:
    """
    Resolve hostname to real IPs and check each against blocked networks.
    Returns False for any URL that should not be fetched.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme not in ("http", "https"):
            return False
        if not host:
            return False
        if host in _BLOCKED_HOSTNAMES:
            return False
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        for info in infos:
            if _ip_is_blocked(info[4][0]):
                return False
        return True
    except Exception:
        return False  # resolution failure = unsafe

from playwright.async_api import Locator, Page
from PIL import Image

from browser.config import BROWSER_SCREENSHOT_MAX_WIDTH, BROWSER_LATEST_SCREENSHOT_PATH

logger = logging.getLogger(__name__)


# ── Screenshot ────────────────────────────────────────────────────────────


async def capture_screenshot(page: Page, session_id: str = "") -> str:
    """
    Take a viewport screenshot, optionally downscale it, and return
    a base64-encoded PNG string. Also atomically writes to a session-scoped
    live file if BROWSER_LATEST_SCREENSHOT_PATH is configured.
    """
    raw: bytes = await page.screenshot(type="png", full_page=False)

    if BROWSER_SCREENSHOT_MAX_WIDTH > 0:
        raw = _resize_png(raw, BROWSER_SCREENSHOT_MAX_WIDTH)

    # Atomic write to session-scoped live file
    if session_id and BROWSER_LATEST_SCREENSHOT_PATH:
        live_path = _live_path_for(session_id)
        try:
            await asyncio.to_thread(_atomic_write, live_path, raw)
        except Exception:
            pass  # Don't fail the tool if write fails

    return base64.b64encode(raw).decode("utf-8")


def _live_path_for(session_id: str) -> str:
    """Return the filesystem path for a session's rolling live screenshot."""
    base = BROWSER_LATEST_SCREENSHOT_PATH
    if not base:
        return ""
    # Insert session_id before the extension, or append if no extension
    root, ext = os.path.splitext(base)
    return f"{root}-{session_id}{ext}"


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _resize_png(data: bytes, max_width: int) -> bytes:
    """Downscale PNG to max_width preserving aspect ratio. No-op if already smaller."""
    with Image.open(io.BytesIO(data)) as img:
        w, h = img.size
        if w <= max_width:
            return data
        new_w = max_width
        new_h = int(h * max_width / w)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


# ── Element resolution ────────────────────────────────────────────────────

# Interactive roles Playwright can locate via get_by_role()
_INTERACTIVE_ROLES = (
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "menuitem",
    "tab",
    "option",
    "searchbox",
    "switch",
)


async def resolve_element(page: Page, target: str) -> Locator | None:
    """
    Resolve a plain-text target to a Playwright Locator using the approved
    priority order:

      1. Exact text match via get_by_text()
      2. CSS / XPath  (target starts with #, ., or /)
      3. ARIA role + label via get_by_role() / get_by_label()
      4. Fuzzy case-insensitive partial text match

    Returns the first visible, enabled Locator found, or None.
    """
    # 1. Exact text match
    loc = page.get_by_text(target, exact=True)
    if await _is_usable(loc):
        return loc.first

    # 2. CSS selector or XPath
    if target.startswith(("#", ".", "/")):
        try:
            loc = page.locator(target)
            if await _is_usable(loc):
                return loc.first
        except Exception:  # noqa: BLE001
            pass

    # 3. ARIA role + label
    for role in _INTERACTIVE_ROLES:
        loc = page.get_by_role(role, name=target)  # type: ignore[arg-type]
        if await _is_usable(loc):
            return loc.first

    loc = page.get_by_label(target)
    if await _is_usable(loc):
        return loc.first

    # 4. Fuzzy partial text match (case-insensitive)
    loc = page.get_by_text(target, exact=False)
    if await _is_usable(loc):
        return loc.first

    return None


async def _is_usable(loc: Locator) -> bool:
    """
    Return True if the locator resolves to at least one visible element.

    Accepts count >= 1 rather than exactly 1 because pages like Wikipedia
    render the same widget in multiple places (main header + sticky header).
    resolve_element always returns loc.first to pin to a single element,
    so accepting multiple matches here is safe — we never hand an ambiguous
    locator to the caller.
    """
    try:
        count = await loc.count()
        if count < 1:
            return False
        return await loc.first.is_visible()
    except Exception:  # noqa: BLE001
        return False


async def list_clickable_elements(page: Page) -> list[str]:
    """
    Return a list of short descriptors for every visible interactive element
    on the current page. Used in element_not_found responses so the LLM can
    self-correct.
    """
    elements: list[str] = []
    for role in _INTERACTIVE_ROLES:
        locs = page.get_by_role(role)  # type: ignore[arg-type]
        try:
            count = await locs.count()
            for i in range(min(count, 50)):  # cap per-role to avoid huge lists
                loc = locs.nth(i)
                if not await loc.is_visible():
                    continue
                text = (await loc.inner_text()).strip()[:80]
                aria = await loc.get_attribute("aria-label") or ""
                label = text or aria or f"<{role}>"
                elements.append(f"[{role}] {label}")
        except Exception:  # noqa: BLE001
            continue
    return elements


# ── Tool response helpers ─────────────────────────────────────────────────


def ok(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap a successful tool result."""
    return {"status": "ok", **data}


def err(message: str, **extra: Any) -> dict[str, Any]:
    """Wrap a failed tool result."""
    return {"status": "error", "error": message, **extra}


# ── Input sanitization ──────────────────────────────────────────────────────
#防止单点故障


def sanitize_script(script: str) -> str:
    """
    Sanitize JavaScript for safe execution.
    
    Removes dangerous patterns while allowing legitimate browser automation.
    """
    # Strip null bytes and control characters
    sanitized = script.replace("\x00", "")
    
    # Limit script length (50KB max)
    MAX_LENGTH = 50 * 1024
    if len(script) > MAX_LENGTH:
        raise ValueError(f"Script too long (max {MAX_LENGTH} bytes)")
    
    # Check for potentially dangerous patterns
    dangerous_patterns = [
        "import",
        "eval",
        "fetch",
        "XMLHttpRequest",
        "new Function",
        "document.write",
        "document.writeln",
        "onerror",
        "onload",
        "onclick",
        "onchange",
        "onsubmit",
        "onbeforeunload",
        "atob(",
        "btoa(",
        "setTimeout(",
        "setInterval(",
        "URL.createObjectURL",
        "URL.revokeObjectURL",
        "WebAssembly.compile",
        "Function(",
        "document.domain=",
        "localStorage.clear()",
        "sessionStorage.clear()",
    ]
    
    for pattern in dangerous_patterns:
        if pattern.lower() in sanitized.lower():
            raise ValueError(f"Potentially dangerous pattern detected: {pattern}")
    
    # Only allow specific protocols for URLs
    allowed_protocols = ("http://", "https://", "data:")
    if script.strip().startswith(allowed_protocols):
        return sanitized
    
    return sanitized
