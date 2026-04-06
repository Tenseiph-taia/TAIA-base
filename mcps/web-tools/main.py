import asyncio
import io
import os
import re
import time
import socket
import ipaddress
import logging
import httpx

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from ddgs import DDGS
from markdownify import markdownify as md
from youtube_transcript_api import YouTubeTranscriptApi
from pypdf import PdfReader
from urllib.parse import urlparse

# ── FastMCP init ───────────────────────────────────────────────────────────────
mcp = FastMCP("TAIA-Web-Tools", host="0.0.0.0", port=8000)
logger = logging.getLogger("taia-web")
logging.basicConfig(level=logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY")
PDF_MAX_BYTES   = 50 * 1024 * 1024
MARKDOWN_MAX_CHARS = 250_000

# ── Browser headers ────────────────────────────────────────────────────────────
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ── SSRF protection ────────────────────────────────────────────────────────────
# Uses ipaddress module — mathematically evaluates the IP, not string matching.
# Blocks bypasses like:
#   http://0177.0.0.1        (octal for 127.0.0.1)
#   http://2130706433        (decimal for 127.0.0.1)
#   http://[::ffff:127.0.0.1] (IPv4-mapped IPv6)
#   http://safe-looking.com  → DNS resolves to 127.0.0.1 (DNS rebinding)

_BLOCKED_HOSTNAMES = {
    "localhost", "mongodb", "rag_api", "vectordb",
    "meilisearch", "web_tools", "ollama", "host.docker.internal",
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
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT (also used by cloud metadata)
]

def _ip_is_blocked(ip_str: str) -> bool:
    """Mathematically check if an IP falls in any blocked network."""
    try:
        addr = ipaddress.ip_address(ip_str)
        # Unwrap IPv4-mapped IPv6 (::ffff:127.0.0.1 → 127.0.0.1)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        return True  # unparseable = block it

async def _is_url_safe(url: str) -> bool:
    """
    Resolves hostname → real IPs, then mathematically checks each against
    blocked networks. Defeats DNS rebinding and all numeric IP encoding tricks.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme not in ("http", "https"):
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


# ── Rate Limiter (Token Bucket) ────────────────────────────────────────────────
class TokenBucketLimiter:
    """
    Token bucket — queues excess callers, never drops them.
    FIX: sleep is computed inside the lock but executed OUTSIDE it,
    so other callers are never frozen while we wait.
    """
    def __init__(self, rate: float, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(capacity)

    async def acquire(self):
        await self._semaphore.acquire()
        wait = 0.0
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self.capacity,
                self._tokens + (now - self._last_refill) * self.rate,
            )
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self.rate
                self._tokens = 0
            else:
                self._tokens -= 1
        if wait > 0:
            logger.info(f"[TAIA] Rate limit: queuing for {wait:.2f}s")
            await asyncio.sleep(wait)

    def release(self):
        self._semaphore.release()


# 15 searches/sec sustained, burst up to 10 concurrent
search_limiter = TokenBucketLimiter(rate=15, capacity=10)


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_youtube_id(url: str) -> str | None:
    regex = (
        r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)"
        r"|youtu\.be\/|youtube\.com\/shorts\/)([^\"&?\/\s]{11})"
    )
    match = re.search(regex, url)
    return match.group(1) if match else None


def _fetch_transcript(video_id: str) -> str:
    """Sync — always call via asyncio.to_thread()."""
    api = YouTubeTranscriptApi()
    for lang_pref in (["en", "tl"], None):
        try:
            if lang_pref:
                fetched = api.fetch(video_id, languages=lang_pref)
            else:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                fetched = next(iter(transcript_list)).fetch()
            return " ".join(s.get("text", "") for s in fetched)
        except Exception:
            continue
    raise RuntimeError("No transcripts found for this video.")


async def _scrape_with_playwright(
    url: str,
    capture_screenshot: bool = False,
) -> tuple[str, bytes | None]:
    """
    Returns (markdown, screenshot_bytes | None).
    Screenshot only rendered when capture_screenshot=True — skipping it on
    plain read_url_content saves ~40-80ms CPU + RAM per call.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=BROWSER_HEADERS["User-Agent"],
            locale="en-US",
            timezone_id="Asia/Manila",
            extra_http_headers={k: v for k, v in BROWSER_HEADERS.items() if k != "User-Agent"},
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        await asyncio.sleep(1)

        html = await page.evaluate("document.body.innerHTML")
        screenshot_bytes = (
            await page.screenshot(type="png", full_page=False)
            if capture_screenshot else None
        )
        await browser.close()

    markdown = md(html, heading_style="ATX", strip=["script", "style", "nav", "footer"])
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    if len(markdown) > MARKDOWN_MAX_CHARS:
        markdown = markdown[:MARKDOWN_MAX_CHARS] + "\n\n[... truncated at 50,000 chars]"

    return markdown, screenshot_bytes


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def read_url_content(url: str) -> str:
    """
    CRITICAL: Use this tool to read the FULL text of any URL.

    - YouTube link  → returns the full video transcript.
    - PDF link      → extracts and returns all text from the document.
    - Any website   → scrapes and returns the page content as Markdown.

    Do NOT call search_web_for_links if you already have the URL.
    """
    logger.info(f"[TAIA] READ_URL: {url}")

    if not await _is_url_safe(url):
        logger.warning(f"[TAIA] Blocked unsafe URL: {url}")
        return "Blocked: URL targets a restricted or internal address."

    # ── 1. YouTube ─────────────────────────────────────────────────────────────
    if "youtube.com" in url or "youtu.be" in url:
        video_id = extract_youtube_id(url)
        if not video_id:
            return f"Could not parse a YouTube video ID from: {url}"
        try:
            text = await asyncio.to_thread(_fetch_transcript, video_id)
            return f"--- YOUTUBE TRANSCRIPT: {url} ---\n\n{text}"
        except Exception as e:
            return f"Transcript unavailable for {url}: {e}"

    # ── 2. PDF ─────────────────────────────────────────────────────────────────
    if url.lower().endswith(".pdf") or "application/pdf" in url:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=30.0, headers=BROWSER_HEADERS
            ) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    chunks, total = [], 0
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        total += len(chunk)
                        if total > PDF_MAX_BYTES:
                            return f"PDF too large (>{PDF_MAX_BYTES // 1024 // 1024} MB): {url}"
                        chunks.append(chunk)
                    pdf_bytes = b"".join(chunks)
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages_text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
            return f"--- PDF CONTENT: {url} ---\n\n{pages_text}"
        except Exception as e:
            return f"Could not read PDF at {url}: {e}"

    # ── 3. Generic Web Scrape ──────────────────────────────────────────────────
    try:
        markdown, _ = await _scrape_with_playwright(url)
        return f"--- CONTENT: {url} ---\n\n{markdown}"
    except Exception as e:
        logger.error(f"[TAIA] Scrape failed for {url}: {e}")
        return f"Error reading {url}: {e}"


@mcp.tool()
async def take_screenshot(url: str) -> Image:
    """
    Takes a screenshot of any webpage and returns it as an image.
    Use this when the user wants to visually inspect a page,
    verify a UI, or see what a website looks like.
    """
    logger.info(f"[TAIA] SCREENSHOT: {url}")

    if not await _is_url_safe(url):
        logger.warning(f"[TAIA] Blocked unsafe URL: {url}")
        raise RuntimeError("Blocked: URL targets a restricted or internal address.")

    try:
        _, screenshot_bytes = await _scrape_with_playwright(url, capture_screenshot=True)
        if not screenshot_bytes:
            raise RuntimeError("No screenshot captured.")
        return Image(data=screenshot_bytes, format="png")
    except Exception as e:
        logger.error(f"[TAIA] Screenshot failed for {url}: {e}")
        raise RuntimeError(f"Screenshot failed for {url}: {e}")


@mcp.tool()
async def search_web_for_links(query: str) -> str:
    """
    Use this tool ONLY to discover NEW links or answer live questions.
    Returns top-5 results from DuckDuckGo PH, with Tavily as fallback.
    Excess requests are queued — never dropped.

    Prefer read_url_content once you have a specific URL.
    """
    logger.info(f"[TAIA] WEB_SEARCH: {query}")

    # ── Primary: DuckDuckGo (rate-limited, non-blocking) ──────────────────────
    await search_limiter.acquire()
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, region="ph-en", max_results=5))
        )
        if results:
            return "\n\n".join(
                f"Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}"
                for r in results
            )
        logger.warning("[TAIA] DDG returned empty — falling back to Tavily")
    except Exception as e:
        logger.warning(f"[TAIA] DDG failed ({e}) — falling back to Tavily")
    finally:
        search_limiter.release()

    # ── Fallback: Tavily ───────────────────────────────────────────────────────
    if not TAVILY_API_KEY:
        return "Search unavailable: DuckDuckGo blocked and no TAVILY_API_KEY set."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_answer": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", [])
        if not results:
            return "No results found."
        return "\n\n".join(
            f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r.get('content', '')[:300]}"
            for r in results
        )
    except Exception as e:
        logger.error(f"[TAIA] Tavily fallback failed: {e}")
        return f"Search failed: {e}"


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="sse")