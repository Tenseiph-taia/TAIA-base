"""
session.py — Session manager for taia-browser-harness.

Owns all Playwright state. Each named session maps to one
BrowserContext + one Page. Sessions expire after idle timeout.
Thread-safe via asyncio.Lock.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from playwright_stealth import Stealth
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from browser.config import (
    BROWSER_DEFAULT_TIMEOUT_MS,
    BROWSER_HEADLESS,
    BROWSER_MAX_SESSIONS,
    BROWSER_NAVIGATION_TIMEOUT_MS,
    BROWSER_PROXY,
    BROWSER_SESSION_TIMEOUT_MINUTES,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
)

logger = logging.getLogger(__name__)


@dataclass
class Session:
    session_id: str
    context: BrowserContext
    page: Page
    owner_id: str = ""
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        """Reset the idle timer."""
        self.last_used_at = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used_at


class SessionManager:
    """
    Lifecycle owner for all browser sessions.

    Usage
    -----
    mgr = SessionManager()
    await mgr.start()          # launches Playwright + Chromium
    session = await mgr.get_or_create("my-session")
    ...
    await mgr.stop()           # closes everything
    """

    # Maximum browser sessions any single transport connection may hold.
    # Prevents one user from consuming the entire session pool.
    MAX_SESSIONS_PER_OWNER = 10

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start Playwright and launch Chromium. Call once at server startup."""
        self._playwright = await async_playwright().start()
        launch_kwargs: dict = {
            "headless": BROWSER_HEADLESS,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox",
                "--no-zygote",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--disable-infobars",
                "--disable-extensions",
                "--disable-component-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-features=Translate,BackForwardCache,AutofillServerCommunication",
                "--disable-browser-side-navigation",
            ],
            "ignore_default_args": ["--enable-automation"],
        }
        if BROWSER_PROXY:
            launch_kwargs["proxy"] = {"server": BROWSER_PROXY}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._reaper_task = asyncio.create_task(
            self._reaper_loop(), name="session-reaper"
        )
        logger.info("SessionManager started (headless=%s)", BROWSER_HEADLESS)

    async def stop(self) -> None:
        """Close all sessions and shut down Chromium. Call once at server shutdown."""
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            for sid in list(self._sessions):
                await self._close_session_unlocked(sid)

        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("SessionManager stopped")

    # ── Public API ────────────────────────────────────────────────────────

    async def get_or_create(self, session_id: str, owner_id: str = "") -> Session:
        """
        Return an existing session or create a new one.

        owner_id — transport session ID of the caller. If the session already
        exists and was created by a different owner, raises PermissionError.
        Raises RuntimeError if any session cap is reached.
        """
        async with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                if owner_id and session.owner_id and session.owner_id != owner_id:
                    raise PermissionError(
                        f"Session '{session_id}' belongs to a different connection."
                    )
                session.touch()
                return session

            if len(self._sessions) >= BROWSER_MAX_SESSIONS:
                raise RuntimeError(
                    f"Global session cap reached ({BROWSER_MAX_SESSIONS}). "
                    "Try again later."
                )

            if owner_id:
                owner_count = sum(
                    1 for s in self._sessions.values() if s.owner_id == owner_id
                )
                if owner_count >= self.MAX_SESSIONS_PER_OWNER:
                    raise RuntimeError(
                        f"Per-connection session cap reached "
                        f"({self.MAX_SESSIONS_PER_OWNER}). "
                        "Close an existing session before opening a new one."
                    )

            session = await self._create_session_unlocked(session_id, owner_id)
            self._sessions[session_id] = session
            logger.info(
                "Session created: %s owner=%s (total=%d)",
                session_id, owner_id[:12] if owner_id else "anon", len(self._sessions),
            )
            return session

    async def get(self, session_id: str, owner_id: str = "") -> Optional[Session]:
        """
        Return an existing session and touch it, or None if not found.
        Raises PermissionError if owner_id is provided and does not match.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if owner_id and session.owner_id and session.owner_id != owner_id:
                raise PermissionError(
                    f"Session '{session_id}' belongs to a different connection."
                )
            session.touch()
            return session

    async def close(self, session_id: str, owner_id: str = "") -> bool:
        """
        Explicitly close a session.
        Returns True if the session existed and was closed, False otherwise.
        Raises PermissionError if owner_id is provided and does not match.
        """
        async with self._lock:
            if session_id not in self._sessions:
                return False
            session = self._sessions[session_id]
            if owner_id and session.owner_id and session.owner_id != owner_id:
                raise PermissionError(
                    f"Session '{session_id}' belongs to a different connection."
                )
            await self._close_session_unlocked(session_id)
            return True

    async def list_sessions(self, owner_id: str = "") -> list[dict]:
        """
        Return a snapshot of active sessions.
        If owner_id is provided, returns only sessions owned by that connection.
        """
        async with self._lock:
            now = time.monotonic()
            sessions = (
                [s for s in self._sessions.values() if s.owner_id == owner_id]
                if owner_id
                else list(self._sessions.values())
            )
            return [
                {
                    "session_id": s.session_id,
                    "created_at_seconds_ago": round(now - s.created_at, 1),
                    "idle_seconds": round(s.idle_seconds(), 1),
                    "timeout_seconds": BROWSER_SESSION_TIMEOUT_MINUTES * 60,
                }
                for s in sessions
            ]
        
    async def get_active_page(self, session_id: str | None = None) -> Page | None:
        """Return the Page for a specific session, or the most recently touched one."""
        async with self._lock:
            if session_id:
                session = self._sessions.get(session_id)
                if session:
                    logger.info("get_active_page: found session '%s' (owner=%s, idle=%.1fs)", 
                                session_id[:12], session.owner_id[:12] if session.owner_id else "anon", 
                                session.idle_seconds())
                    return session.page
                else:
                    logger.warning("get_active_page: session '%s' NOT FOUND. Active sessions: %s", 
                                  session_id[:12], [s[:12] for s in self._sessions.keys()])
                    return None
            if not self._sessions:
                logger.warning("get_active_page: no active sessions")
                return None
            latest = max(self._sessions.values(), key=lambda s: s.last_used_at)
            logger.info("get_active_page: returning most recent session '%s'", latest.session_id[:12])
            return latest.page

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _create_session_unlocked(self, session_id: str, owner_id: str = "") -> Session:
        """Must be called with self._lock held."""
        assert self._browser is not None, "SessionManager not started"

        context: BrowserContext = await self._browser.new_context(
            viewport={
                "width": BROWSER_VIEWPORT_WIDTH,
                "height": BROWSER_VIEWPORT_HEIGHT,
            },
            locale="en-US",
            timezone_id="Asia/Manila",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            color_scheme="light",
            reduced_motion="no-preference",
            device_scale_factor=1,
            has_touch=False,
            permissions=["geolocation"],
            geolocation={"latitude": 14.5995, "longitude": 120.9842},
        )
        context.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(BROWSER_NAVIGATION_TIMEOUT_MS)

        page: Page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        return Session(
            session_id=session_id,
            context=context,
            page=page,
            owner_id=owner_id,
        )

    async def _close_session_unlocked(self, session_id: str) -> None:
        """Must be called with self._lock held."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        try:
            await session.context.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error closing session %s: %s", session_id, exc)
        logger.info("Session closed: %s (total=%d)", session_id, len(self._sessions))

    async def _reaper_loop(self) -> None:
        """Background task — evicts sessions that have been idle too long."""
        timeout_secs = BROWSER_SESSION_TIMEOUT_MINUTES * 60
        while True:
            await asyncio.sleep(60)  # check every minute
            async with self._lock:
                expired = [
                    sid
                    for sid, s in self._sessions.items()
                    if s.idle_seconds() >= timeout_secs
                ]
                for sid in expired:
                    logger.info("Reaping idle session: %s", sid)
                    await self._close_session_unlocked(sid)
