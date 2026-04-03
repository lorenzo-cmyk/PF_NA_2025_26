"""Download and cache Tailwind CSS locally."""

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def ensure_tailwind() -> bool:
    """
    Ensure Tailwind CSS is available locally.

    Returns True if successful, False if failed.
    """
    static_dir = Path(__file__).resolve().parent / "templates" / "static"
    tailwind_file = static_dir / "tailwind.min.js"

    if tailwind_file.exists():
        log.info("Tailwind CSS already cached at %s", tailwind_file)
        return True

    # Create static directory if it doesn't exist
    static_dir.mkdir(parents=True, exist_ok=True)

    # Download Tailwind CSS
    tailwind_url = "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"
    log.info("Downloading Tailwind CSS from %s …", tailwind_url)

    try:
        import urllib.request

        urllib.request.urlretrieve(tailwind_url, str(tailwind_file))
        log.info("Tailwind CSS downloaded successfully to %s", tailwind_file)
        return True
    except Exception as e:
        log.error("Failed to download Tailwind CSS: %s", e)
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    success = ensure_tailwind()
    sys.exit(0 if success else 1)
