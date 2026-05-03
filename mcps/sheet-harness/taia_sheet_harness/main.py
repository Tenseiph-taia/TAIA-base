import asyncio
import logging
import os

from .server import mcp

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    """Start MCP server (port 8006) for TAIA orchestration."""
    mcp_port = int(os.getenv("PORT_MCP", os.getenv("PORT", "8006")))
    host = os.getenv("HOST", "0.0.0.0")

    log.info("Starting TAIA Sheet Harness (MCP only)...")
    log.info("MCP server (SSE) on port %s", mcp_port)

    mcp_task = asyncio.create_task(
        asyncio.to_thread(mcp.run, transport="sse", host=host, port=mcp_port)
    )

    await mcp_task


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()