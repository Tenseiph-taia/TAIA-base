import asyncio
import logging
import os
import threading
import uvicorn

from .server import mcp
from .download_server import download_app 

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


def _start_download_server(host: str, port: int):
    """Run the FastAPI download app in a daemon thread."""
    config = uvicorn.Config(download_app, host=host, port=port)
    server = uvicorn.Server(config)
    log.info("Download server starting on %s:%d", host, port)
    server.run()  # synchronous, runs until the thread dies


def run() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    mcp_port = int(os.getenv("PORT", "8006"))
    download_port = int(os.getenv("DOWNLOAD_PORT", "8007"))

    # Start download server in a background daemon thread
    thread = threading.Thread(
        target=_start_download_server,
        args=(host, download_port),
        daemon=True,
    )
    thread.start()

    # Start the MCP SSE server (blocking)
    log.info("MCP server (SSE) listening on %s:%d", host, mcp_port)
    mcp.run(transport="sse", host=host, port=mcp_port)


if __name__ == "__main__":
    run()