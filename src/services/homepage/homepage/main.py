"""Homepage service – entry point.

Starts the FastAPI application serving the homepage.
"""

from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from homepage.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

cfg = Config()
app = FastAPI(title="gBOAR Homepage")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the homepage with links to all services."""
    sections = {
        "extreme-edge": {"title": "Extreme-Edge", "links": []},
        "edge": {"title": "Edge", "links": []},
        "cloud": {"title": "Cloud", "links": []},
    }
    for link in cfg.links():
        sections[link.section]["links"].append(link)

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "sections": sections},
    )


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


def main() -> None:
    """Start the uvicorn server."""
    log.info("Starting gBOAR Homepage on %s:%s", cfg.host, cfg.port)
    uvicorn.run(
        "homepage.main:app",
        host=cfg.host,
        port=cfg.port,
        log_level="info",
    )
