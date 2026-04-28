"""
tools.py — All MCP tool definitions and handlers for taia-browser-harness.

Each tool:
  - Accepts a session_id (except browser_sessions)
  - Resolves the session via SessionManager
  - Performs its action
  - Captures a screenshot (where applicable)
  - Returns a structured dict via ok() / err()

Tools
-----
  browser_open        Navigate to a URL
  browser_click       Click an element by text / selector / role
  browser_type        Type text into an element, optionally submit
  browser_scroll      Scroll the page up/down/left/right
  browser_screenshot  Capture current viewport
  browser_extract     Extract visible text or structured data
  browser_wait        Wait for a condition (load / selector / text / idle)
  browser_close       Close a named session
  browser_sessions    List all active sessions
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from browser.session import SessionManager
from browser.utils import (
    is_url_safe,
    capture_screenshot,
    err,
    list_clickable_elements,
    ok,
    resolve_element,
    sanitize_script,
)

logger = logging.getLogger(__name__)


# ── Tool handlers ─────────────────────────────────────────────────────────


async def handle_browser_open(
    mgr: SessionManager,
    session_id: str,
    url: str,
    owner_id: str = "",
) -> dict[str, Any]:
    """Navigate to url. Creates the session if it does not exist."""
    try:
        session = await mgr.get_or_create(session_id, owner_id)
    except (RuntimeError, PermissionError) as exc:
        return err(str(exc))

    if not await is_url_safe(url):
        return err(
            f"Blocked: '{url}' targets a restricted or internal address."
        )

    try:
        response = await session.page.goto(url, wait_until="load")
        status = response.status if response else None
        title = await session.page.title()
        screenshot = await capture_screenshot(session.page, session_id)
        session.touch()
        return ok(
            {
                "url": session.page.url,
                "title": title,
                "http_status": status,
                "screenshot": screenshot,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser_open failed: %s", exc)
        return err(f"Navigation failed: {exc}")


async def handle_browser_click(
    mgr: SessionManager,
    session_id: str,
    target: str,
    owner_id: str = "",
) -> dict[str, Any]:
    """Click an element identified by target."""
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")

    loc = await resolve_element(session.page, target)
    if loc is None:
        clickable = await list_clickable_elements(session.page)
        return err(
            f"Element not found: '{target}'",
            clickable_elements=clickable,
        )

    try:
        await loc.click()
        await session.page.wait_for_load_state("domcontentloaded")
    except Exception as click_exc:
        exc_str = str(click_exc).lower()
        if any(k in exc_str for k in ("detached", "closed", "target", "destroyed")):
            await asyncio.sleep(0.5)
            loc = await resolve_element(session.page, target)
            if loc is None:
                clickable = await list_clickable_elements(session.page)
                return err(
                    f"Element '{target}' disappeared after navigation.",
                    clickable_elements=clickable,
                )
            await loc.click()
            await session.page.wait_for_load_state("domcontentloaded")
        else:
            logger.exception("browser_click failed: %s", click_exc)
            return err(f"Click failed: {click_exc}")

    title = await session.page.title()
    screenshot = await capture_screenshot(session.page, session_id)
    session.touch()
    return ok(
        {
            "clicked": target,
            "url": session.page.url,
            "title": title,
            "screenshot": screenshot,
        }
    )


async def handle_browser_type(
    mgr: SessionManager,
    session_id: str,
    target: str,
    text: str,
    submit: bool = False,
    clear: bool = True,
    owner_id: str = "",
) -> dict[str, Any]:
    """
    Type text into an element. Optionally press Enter to submit.

    session_id: Active session to use.
    target: Input element — text, selector, XPath, or ARIA label.
    text: Text to type into the element.
    submit: Press Enter after typing. Default false.
    clear: Clear existing content before typing. Default true.
           Set to false to append to existing text.
    """
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")

    loc = await resolve_element(session.page, target)
    if loc is None:
        clickable = await list_clickable_elements(session.page)
        return err(
            f"Element not found: '{target}'",
            clickable_elements=clickable,
        )

    try:
        await loc.click()
        if clear:
            await loc.fill(text)
        else:
            await loc.type(text)
        if submit:
            await loc.press("Enter")
            await session.page.wait_for_load_state("domcontentloaded")
    except Exception as type_exc:
        exc_str = str(type_exc).lower()
        if any(k in exc_str for k in ("detached", "closed", "target", "destroyed")):
            await asyncio.sleep(0.5)
            loc = await resolve_element(session.page, target)
            if loc is None:
                clickable = await list_clickable_elements(session.page)
                return err(
                    f"Element '{target}' disappeared after navigation.",
                    clickable_elements=clickable,
                )
            await loc.click()
            if clear:
                await loc.fill(text)
            else:
                await loc.type(text)
            if submit:
                await loc.press("Enter")
                await session.page.wait_for_load_state("domcontentloaded")
        else:
            logger.exception("browser_type failed: %s", type_exc)
            return err(f"Type failed: {type_exc}")

    title = await session.page.title()
    screenshot = await capture_screenshot(session.page, session_id)
    session.touch()
    return ok(
        {
            "typed_into": target,
            "text": text,
            "submitted": submit,
            "url": session.page.url,
            "title": title,
            "screenshot": screenshot,
        }
    )


async def handle_browser_scroll(
    mgr: SessionManager,
    session_id: str,
    direction: str,
    amount: int = 3,
    owner_id: str = "",
) -> dict[str, Any]:
    """
    Scroll the page.
    direction: 'up' | 'down' | 'left' | 'right'
    amount: number of 'ticks' (each tick = 300px)
    """
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")

    direction = direction.lower().strip()
    if direction not in ("up", "down", "left", "right"):
        return err(
            f"Invalid direction '{direction}'. Must be one of: up, down, left, right."
        )

    px = amount * 300
    x_delta = px if direction == "right" else (-px if direction == "left" else 0)
    y_delta = px if direction == "down" else (-px if direction == "up" else 0)

    try:
        await session.page.mouse.wheel(x_delta, y_delta)
        screenshot = await capture_screenshot(session.page, session_id)
        session.touch()
        return ok(
            {
                "direction": direction,
                "amount": amount,
                "screenshot": screenshot,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser_scroll failed: %s", exc)
        return err(f"Scroll failed: {exc}")


async def handle_browser_screenshot(
    mgr: SessionManager,
    session_id: str,
    owner_id: str = "",
) -> dict[str, Any]:
    """Capture and return the current viewport as a base64 PNG."""
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")

    try:
        screenshot = await capture_screenshot(session.page, session_id)
        title = await session.page.title()
        session.touch()
        return ok(
            {
                "url": session.page.url,
                "title": title,
                "screenshot": screenshot,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser_screenshot failed: %s", exc)
        return err(f"Screenshot failed: {exc}")


async def handle_browser_extract(
    mgr: SessionManager,
    session_id: str,
    query: str,
    owner_id: str = "",
) -> dict[str, Any]:
    """
    Extract visible text content from the current page.

    The query is used as a hint — it is included in the response so the
    calling LLM can filter/interpret the raw text. No client-side NLP is
    performed here; the LLM does the reasoning.
    """
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")

    try:
        # Extract all visible text via the accessibility tree — more reliable
        # than innerHTML parsing and works across SPAs.
        text_content: str = await session.page.evaluate(
            """() => {
                const MAX_NODES = 5000;
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode(node) {
                            const parent = node.parentElement;
                            if (!parent) return NodeFilter.FILTER_REJECT;
                            const style = window.getComputedStyle(parent);
                            if (style.display === 'none' || style.visibility === 'hidden')
                                return NodeFilter.FILTER_REJECT;
                            const text = node.textContent.trim();
                            return text.length > 0
                                ? NodeFilter.FILTER_ACCEPT
                                : NodeFilter.FILTER_REJECT;
                        }
                    }
                );
                const chunks = [];
                let node;
                let count = 0;
                while ((node = walker.nextNode()) && count++ < MAX_NODES) {
                    chunks.push(node.textContent.trim());
                }
                if (count >= MAX_NODES) {
                    chunks.push('... [truncated: exceeded ' + MAX_NODES + ' text nodes]');
                }
                return chunks.join('\\n');
            }"""
        )
        screenshot = await capture_screenshot(session.page, session_id)
        session.touch()
        return ok(
            {
                "query": query,
                "url": session.page.url,
                "title": await session.page.title(),
                "text_content": text_content[:50_000],  # hard cap — LLM context safety
                "screenshot": screenshot,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser_extract failed: %s", exc)
        return err(f"Extract failed: {exc}")


async def handle_browser_wait(
    mgr: SessionManager,
    session_id: str,
    condition: str,
    timeout: int = 10,
    owner_id: str = "",
) -> dict[str, Any]:
    """
    Wait for a condition before continuing.

    condition values
    ----------------
    'load'          — wait for the load event
    'domcontent'    — wait for DOMContentLoaded
    'networkidle'   — wait for network to go quiet
    'idle'          — alias for networkidle
    anything else   — treated as a CSS selector to wait for
    """
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")

    timeout_ms = timeout * 1000
    condition_lower = condition.lower().strip()

    try:
        if condition_lower in ("load",):
            await session.page.wait_for_load_state("load", timeout=timeout_ms)
        elif condition_lower in ("domcontent", "domcontentloaded"):
            await session.page.wait_for_load_state(
                "domcontentloaded", timeout=timeout_ms
            )
        elif condition_lower in ("networkidle", "idle"):
            await session.page.wait_for_load_state(
                "networkidle", timeout=timeout_ms
            )
        else:
            # Treat as CSS selector
            try:
                await session.page.wait_for_selector(condition, timeout=timeout_ms)
            except Exception as selector_exc:
                # Distinguish invalid selector from simply not found
                try:
                    await session.page.locator(condition).count()
                except Exception:
                    return err(
                        f"Invalid CSS selector: '{condition}'.",
                        detail=str(selector_exc),
                    )
                return err(
                    f"Selector '{condition}' not found within {timeout}s.",
                    detail=str(selector_exc),
                )

        screenshot = await capture_screenshot(session.page, session_id)
        session.touch()
        return ok(
            {
                "condition": condition,
                "url": session.page.url,
                "title": await session.page.title(),
                "screenshot": screenshot,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser_wait failed: %s", exc)
        return err(f"Wait timed out or failed: {exc}")


async def handle_browser_close(
    mgr: SessionManager,
    session_id: str,
    owner_id: str = "",
) -> dict[str, Any]:
    """Close a named session and release its resources."""
    try:
        closed = await mgr.close(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if not closed:
        return err(f"Session '{session_id}' not found.")
    return ok({"closed": session_id})


async def handle_browser_sessions(
    mgr: SessionManager,
    owner_id: str = "",
) -> dict[str, Any]:
    """Return a list of sessions owned by this connection."""
    sessions = await mgr.list_sessions(owner_id)
    return ok({"sessions": sessions, "count": len(sessions)})


async def handle_browser_click_at(
    mgr: SessionManager,
    session_id: str,
    x: int,
    y: int,
    owner_id: str = "",
) -> dict[str, Any]:
    """Click at specific (x, y) coordinates on the page."""
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")

    try:
        await session.page.mouse.click(x, y)
        await session.page.wait_for_load_state("domcontentloaded")
        screenshot = await capture_screenshot(session.page, session_id)
        session.touch()
        return ok(
            {
                "clicked_at": f"({x}, {y})",
                "url": session.page.url,
                "title": await session.page.title(),
                "screenshot": screenshot,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser_click_at failed: %s", exc)
        return err(f"Click at ({x}, {y}) failed: {exc}")


async def handle_browser_evaluate(
    mgr: SessionManager,
    session_id: str,
    script: str,
    owner_id: str = "",
) -> dict[str, Any]:
    """
    Evaluate JavaScript in the page context and return the JSON-serializable result.
    """
    try:
        # Sanitize input script
        sanitized_script = sanitize_script(script)
    except ValueError as exc:
        return err(f"Invalid script: {exc}")
    
    try:
        session = await mgr.get(session_id, owner_id)
    except PermissionError as exc:
        return err(str(exc))
    if session is None:
        return err(f"Session '{session_id}' not found. Call browser_open first.")
    
    try:
        result = await session.page.evaluate(sanitized_script)
        screenshot = await capture_screenshot(session.page, session_id)
        session.touch()
        return ok(
            {
                "result": result,
                "url": session.page.url,
                "title": await session.page.title(),
                "screenshot": screenshot,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser_evaluate failed: %s", exc)
        return err(f"Evaluate failed: {exc}")