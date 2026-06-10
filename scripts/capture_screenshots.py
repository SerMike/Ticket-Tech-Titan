"""capture_screenshots.py — Full-page README screenshots of the dashboard.

Streamlit scrolls inside a nested container, so browser "full page"
screenshot tools only capture one viewport. This script sizes the
viewport to the page's real content height so nothing scrolls, then
captures docs/screenshots/queue.png and analytics.png.

Requires the dashboard running on localhost:8501 and a local Edge
install (uses Playwright's channel="msedge", no browser download).

    python scripts/capture_screenshots.py
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8501"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
WIDTH = 1440


def settle(page, seconds=3.0):
    page.wait_for_load_state("networkidle")
    time.sleep(seconds)


def fit_viewport(page):
    """Grow the viewport to the main container's full content height."""
    height = page.evaluate(
        "document.querySelector('[data-testid=\"stMainBlockContainer\"]').scrollHeight"
    )
    page.set_viewport_size({"width": WIDTH, "height": min(height + 100, 4500)})
    settle(page, 3.0)  # let Plotly charts re-render at the new size


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(
            color_scheme="dark",
            viewport={"width": WIDTH, "height": 1100},
        )
        page = context.new_page()

        # --- Queue page: hide unevaluated tickets so AI categories show ---
        page.goto(f"{BASE}/queue")
        settle(page)
        chip = page.locator('span[data-baseweb="tag"]', has_text="Not yet evaluated")
        if chip.count():
            chip.first.locator("svg").click()
            settle(page)
        fit_viewport(page)
        page.screenshot(path=str(OUT / "queue.png"))
        print(f"queue.png       {page.viewport_size}")

        # --- Analytics page ---
        page.set_viewport_size({"width": WIDTH, "height": 1100})
        page.goto(f"{BASE}/analytics")
        settle(page)
        fit_viewport(page)
        page.screenshot(path=str(OUT / "analytics.png"))
        print(f"analytics.png   {page.viewport_size}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
