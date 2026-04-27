"""
server.py — MCP SSE entry point for taia-browser-harness.

Uses SseServerTransport directly (consistent with taia-web-tools pattern).

Session ownership — correct implementation
------------------------------------------
Tool calls execute inside _mcp._mcp_server.run() which runs in the GET /sse
handler Task (Task A). ContextVars set in Task A are visible to all code in
that task, including every tool dispatch.

The fix: generate a per-connection owner token in the /sse handler, set the
ContextVar BEFORE calling connect_sse, then tool handlers read it via
get_owner_id(). No POST interception, no shared dicts, no key mismatches.

Sequence per connection:
  1. GET /sse arrives → Task A starts
  2. Task A: owner_token = uuid4().hex  ← generate here
  3. Task A: _current_owner.set(owner_token)  ← set in THIS task
  4. Task A: connect_sse(...) → _mcp_server.run(...)
  5. Task A: tool calls dispatch → get_owner_id() returns owner_token ✓

Initialisation
--------------
SessionManager starts lazily on first tool call guarded by a lock.
FastMCP/SseServerTransport fires multiple SSE connections at startup —
a lifespan-based start() would launch multiple Chromium instances.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import sys
import urllib.parse
import uuid

from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.responses import Response

from browser.session import SessionManager
from browser.tools import (
    handle_browser_click,
    handle_browser_click_at,
    handle_browser_close,
    handle_browser_evaluate,
    handle_browser_extract,
    handle_browser_open,
    handle_browser_screenshot,
    handle_browser_scroll,
    handle_browser_sessions,
    handle_browser_type,
    handle_browser_wait,
)
from browser.utils import sanitize_script

from browser.config import (
    BROWSER_LATEST_SCREENSHOT_PATH,
    BROWSER_VIEWPORT_WIDTH,
    BROWSER_VIEWPORT_HEIGHT,
)
from browser.utils import _live_path_for
from browser.ratelimit import RateLimiter, BurstLimiter

# ── Logging ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("taia-browser-harness")

# ── Security configuration ──────────────────────────────────────────────────
# Rate limiting thresholds
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("BROWSER_RATE_LIMIT_MAX", "100"))
RATE_LIMIT_REFILL_RATE = float(os.environ.get("BROWSER_RATE_LIMIT_REFILL", "10.0"))
BURST_LIMIT_MAX = int(os.environ.get("BROWSER_BURST_LIMIT_MAX", "20"))
BURST_LIMIT_WINDOW = int(os.environ.get("BROWSER_BURST_LIMIT_WINDOW", "60"))

# Playwright browsers path (for non-root user)
PLAYWRIGHT_BROWSERS_PATH = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/playwright-browsers")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_BROWSERS_PATH

# Security logger for audit events
security_logger = logging.getLogger("security")

# ── Owner identity ContextVar ─────────────────────────────────────────────
# Set once per SSE connection in the /sse handler Task before connect_sse.
# Tool calls run in the same Task and read it via get_owner_id().

_current_owner: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_owner", default=""
)


def get_owner_id() -> str:
    """Return the owner token for the current SSE connection."""
    return _current_owner.get()


def _live_url(session_id: str = "") -> str:
    """Return the public URL for a session's live viewport."""
    base = os.environ.get("BROWSER_LIVE_PUBLIC_URL", "http://localhost:8005/live.mjpeg")
    if session_id:
        # URL-encode the session ID to handle special characters
        encoded = urllib.parse.quote(session_id, safe='')
        return f"{base}?session={encoded}"
    return base


def _inject_live_url(result: dict, session_id: str = "") -> dict:
    """Add the session-scoped live viewport URL and viewport dimensions."""
    if session_id:
        result["live_viewport_url"] = _live_url(session_id)
    result["viewport_width"] = BROWSER_VIEWPORT_WIDTH
    result["viewport_height"] = BROWSER_VIEWPORT_HEIGHT
    return result


# ── Session manager singleton — lazy init ─────────────────────────────────

# ── Rate limiters ─────────────────────────────────────────────────
_rate_limiter = RateLimiter(
    max_requests=RATE_LIMIT_MAX_REQUESTS,
    refill_rate=RATE_LIMIT_REFILL_RATE,
)
_burst_limiter = BurstLimiter(
    max_burst=BURST_LIMIT_MAX,
    window_seconds=BURST_LIMIT_WINDOW,
)

_mgr = SessionManager()
_mgr_lock = asyncio.Lock()


async def _ensure_started() -> None:
    """Start SessionManager exactly once (double-checked locking)."""
    if _mgr._browser is not None:
        return
    async with _mgr_lock:
        if _mgr._browser is None:
            await _mgr.start()
            logger.info("SessionManager initialised on first tool call")


# ── FastMCP server ────────────────────────────────────────────────

_mcp = FastMCP(
    "taia-browser-harness",
    host="0.0.0.0",
    port=8005,
)

# ── Screenshot helper ─────────────────────────────────────────────────────


def _split_screenshot(result: dict) -> list:
    """
    Strip the screenshot from the result dict and return only the JSON string.

    Static screenshots are no longer sent as Image content items because they
    caused a series of static images to appear in chat for every tool call.
    The live viewport (polled from /live.png) provides continuous visual
    feedback instead.

    The screenshot bytes are discarded here; the live file written by
    capture_screenshot() in utils.py is what the viewport polls.
    """
    result.pop("screenshot", None)
    return [json.dumps(result)]


# ── Tool registrations ────────────────────────────────────────────────────


@_mcp.tool()
async def browser_open(session_id: str, url: str) -> list:
    """
    Open a URL in a browser session. Creates the session if it does not exist.
    Returns the page title, final URL, HTTP status, and a screenshot.

    session_id: Unique name for this browser session.
    url: Fully-qualified URL to navigate to (include https://).
    """
    await _ensure_started()
    result = await handle_browser_open(_mgr, session_id, url, get_owner_id())
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_click(session_id: str, target: str) -> list:
    """
    Click an element on the current page.
    target can be visible text, a CSS selector (#id / .class),
    an XPath (//*), or an ARIA label.
    On failure returns a list of clickable elements for self-correction.

    session_id: Active session to use.
    target: Element to click — text, selector, XPath, or ARIA label.
    """
    await _ensure_started()
    result = await handle_browser_click(_mgr, session_id, target, get_owner_id())
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_type(
    session_id: str,
    target: str,
    text: str,
    submit: bool = False,
    clear: bool = True,
) -> list:
    """
    Type text into an input element. Optionally press Enter to submit.

    session_id: Active session to use.
    target: Input element — text, selector, XPath, or ARIA label.
    text: Text to type into the element.
    submit: Press Enter after typing. Default false.
    clear: Clear existing content before typing. Default true.
    """
    await _ensure_started()
    result = await handle_browser_type(
        _mgr, session_id, target, text, submit, clear, get_owner_id()
    )
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_scroll(
    session_id: str,
    direction: str,
    amount: int = 3,
) -> list:
    """
    Scroll the page in a given direction.

    session_id: Active session to use.
    direction: One of: up, down, left, right.
    amount: Number of scroll ticks (each ~300px). Default 3.
    """
    await _ensure_started()
    result = await handle_browser_scroll(
        _mgr, session_id, direction, amount, get_owner_id()
    )
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_screenshot(session_id: str) -> list:
    """
    Capture the current viewport and return it as an inline image.

    session_id: Active session to use.
    """
    await _ensure_started()
    result = await handle_browser_screenshot(_mgr, session_id, get_owner_id())
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_extract(session_id: str, query: str) -> list:
    """
    Extract all visible text from the current page.
    Provide a query describing what you are looking for — it is passed
    through to help you filter the returned text_content.

    session_id: Active session to use.
    query: What data you want to extract (used as a hint).
    """
    await _ensure_started()
    result = await handle_browser_extract(_mgr, session_id, query, get_owner_id())
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_wait(
    session_id: str,
    condition: str,
    timeout: int = 10,
) -> list:
    """
    Wait for a page condition before proceeding.
    Use 'load', 'domcontent', or 'networkidle' for load states,
    or pass a CSS selector to wait for a specific element to appear.

    session_id: Active session to use.
    condition: 'load' | 'domcontent' | 'networkidle' | 'idle' or a CSS selector.
    timeout: Seconds to wait before giving up. Default 10.
    """
    await _ensure_started()
    result = await handle_browser_wait(
        _mgr, session_id, condition, timeout, get_owner_id()
    )
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_close(session_id: str) -> str:
    """
    Close a browser session and release its resources.

    session_id: Session to close.
    """
    await _ensure_started()
    result = await handle_browser_close(_mgr, session_id, get_owner_id())
    return json.dumps(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_sessions() -> str:
    """
    List browser sessions belonging to the current connection.
    """
    await _ensure_started()
    result = await handle_browser_sessions(_mgr, get_owner_id())
    return json.dumps(_inject_live_url(result, ""))


@_mcp.tool()
async def browser_click_at(session_id: str, x: int, y: int) -> list:
    """
    Click at specific (x, y) pixel coordinates on the page.
    Use this when you need precise coordinate-based clicking.

    session_id: Active session to use.
    x: Horizontal pixel coordinate.
    y: Vertical pixel coordinate.
    """
    await _ensure_started()
    result = await handle_browser_click_at(_mgr, session_id, x, y, get_owner_id())
    return _split_screenshot(_inject_live_url(result, session_id))


@_mcp.tool()
async def browser_evaluate(session_id: str, script: str) -> list:
    """
    Execute JavaScript in the page context and return the result.
    Use this to access window variables, manipulate the DOM, or extract
    data that is not visible in the rendered HTML.

    session_id: Active session to use.
    script: JavaScript expression to evaluate. Must return a JSON-serializable value.
    """
    await _ensure_started()
    result = await handle_browser_evaluate(_mgr, session_id, script, get_owner_id())
    return _split_screenshot(_inject_live_url(result, session_id))


# ── ASGI app ──────────────────────────────────────────────────────────


def build_app():
    """
    Build the ASGI application.

    Key design: owner token is generated and set into _current_owner
    BEFORE connect_sse is called. This means it is set in the /sse
    handler Task (Task A) — the same task where all tool calls execute.
    ContextVars are inherited within a task, so get_owner_id() returns
    the correct token for every tool call on this connection.
    """
    sse = SseServerTransport("/messages/")

    async def handle_sse(scope, receive, send):
        owner_token = uuid.uuid4().hex
        _current_owner.set(owner_token)
        remote_addr = scope.get("client", ("unknown", 0))[0]
        security_logger.info("SSE connection established owner=%s remote=%s", owner_token[:12], remote_addr)
        
        try:
            # Check rate limits before accepting connection
            if not await _burst_limiter.check(owner_token):
                security_logger.warning("Rate limit exceeded for connection owner=%s", owner_token[:12])
                from starlette.responses import JSONResponse
                resp = JSONResponse(
                    {"error": "Rate limit exceeded"},
                    status_code=429,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                    },
                )
                await resp(scope, receive, send)
                return
            
            # Consume rate limit token
            if not await _rate_limiter.check_and_consume(owner_token):
                security_logger.warning("Token bucket exhausted for connection owner=%s", owner_token[:12])
                from starlette.responses import JSONResponse
                resp = JSONResponse(
                    {"error": "Rate limit exceeded"},
                    status_code=429,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                    },
                )
                await resp(scope, receive, send)
                return
            
            async with sse.connect_sse(scope, receive, send) as (read_stream, write_stream):
                await _mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    _mcp._mcp_server.create_initialization_options(),
                )
        finally:
            _current_owner.set("")

    async def _serve_live_png(scope, receive, send):
        from urllib.parse import parse_qs

        method = scope.get("method", "GET")
        if method == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"access-control-allow-origin", b"*"],
                    [b"access-control-allow-methods", b"GET, OPTIONS"],
                ],
            })
            await send({"type": "http.response.body", "body": b""})
            return

        query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
        query_params = parse_qs(query_string)
        session_ids = query_params.get("session", [])

        body = b""
        status = 200
        headers = [
            [b"content-type", b"image/png"],
            [b"cache-control", b"no-cache, no-store, must-revalidate"],
            [b"access-control-allow-origin", b"*"],
        ]

        if session_ids:
            session_id = session_ids[0]
            live_path = _live_path_for(session_id)
            if live_path and os.path.exists(live_path):
                body = await asyncio.to_thread(lambda: open(live_path, "rb").read())
            else:
                # Fallback: capture from the specific session's page on-demand
                page = await _mgr.get_active_page(session_id)
                if page:
                    body = await page.screenshot(type="png", full_page=False)
                else:
                    status = 503
                    body = b"Session not active"
                    headers[0] = [b"content-type", b"text/plain"]
        else:
            # No session specified — return the most recently active session
            page = await _mgr.get_active_page()
            if page:
                body = await page.screenshot(type="png", full_page=False)
            else:
                status = 503
                body = b"No active session"
                headers[0] = [b"content-type", b"text/plain"]

        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _serve_live_mjpeg(scope, receive, send):
        from urllib.parse import parse_qs

        query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
        query_params = parse_qs(query_string)
        session_ids = query_params.get("session", [])

        if not session_ids:
            logger.warning("MJPEG request missing session parameter")
            await send({
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    [b"content-type", b"text/plain"],
                    [b"access-control-allow-origin", b"*"],
                ],
            })
            await send({"type": "http.response.body", "body": b"Missing session"})
            return

        session_id = session_ids[0]
        logger.info("MJPEG stream requested for session: %s", session_id[:12] if session_id else "none")
        
        # Retry logic: session might be initializing
        page = None
        for attempt in range(5):
            page = await _mgr.get_active_page(session_id)
            if page:
                break
            logger.warning("MJPEG attempt %d: session '%s' not found, retrying...", attempt + 1, session_id[:12])
            await asyncio.sleep(0.2)
        
        if not page:
            logger.error("MJPEG failed: session '%s' not found after retries. Active sessions: %s", 
                         session_id[:12], list(_mgr._sessions.keys())[:5] if hasattr(_mgr, '_sessions') else "unknown")
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    [b"content-type", b"text/plain"],
                    [b"access-control-allow-origin", b"*"],
                ],
            })
            await send({"type": "http.response.body", "body": b"Session not active"})
            return
        
        logger.info("MJPEG stream starting for session: %s", session_id[:12])

        boundary = b"--frame"
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"multipart/x-mixed-replace; boundary=--frame"],
                [b"cache-control", b"no-cache, no-store, must-revalidate"],
                [b"access-control-allow-origin", b"*"],
            ],
        })

        try:
            retry_count = 0
            max_retries = 3
            while True:
                try:
                    frame = await page.screenshot(type="jpeg", full_page=False, quality=80)
                    await send({
                        "type": "http.response.body",
                        "body": (
                            b"\r\n" + boundary + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                            b"\r\n"
                            + frame
                            + b"\r\n"
                        ),
                        "more_body": True,
                    })
                    retry_count = 0  # Reset on success
                    await asyncio.sleep(0.1)  # 10 fps
                except Exception:
                    retry_count += 1
                    if retry_count < max_retries:
                        # Quick retry for transient errors
                        await asyncio.sleep(0.05)
                        continue
                    else:
                        # Longer wait before trying again
                        await asyncio.sleep(0.5)
                        retry_count = 0
                        continue
        except Exception:
            # Client disconnected — stop streaming
            pass
        finally:
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return

        path = scope.get("path", "").rstrip("/")

        if path == "/sse":
            await handle_sse(scope, receive, send)
        elif path == "/messages" or path.startswith("/messages/"):
            await sse.handle_post_message(scope, receive, send)
        elif path == "/health":
            # Health check endpoint for load balancer / monitoring
            status = 200 if _mgr._browser is not None else 503
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"access-control-allow-origin", b"*"],
                ],
            })
            body = json.dumps({
                "status": "healthy" if status == 200 else "starting",
                "sessions": len(_mgr._sessions) if _mgr._browser else 0,
            }).encode()
            await send({"type": "http.response.body", "body": body})
        elif path == "/live.png":
            await _serve_live_png(scope, receive, send)
        elif path == "/live.mjpeg":
            await _serve_live_mjpeg(scope, receive, send)
        else:
            resp = Response("Not found", status_code=404)
            await resp(scope, receive, send)

    return app


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        build_app(),
        host="0.0.0.0",
        port=8005,
        loop="asyncio",
        log_level="info",
    )