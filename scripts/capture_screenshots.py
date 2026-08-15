"""capture_screenshots.py — Full-page README screenshots of the dashboard.

The dashboard is a single-page app: the three views are swapped
client-side rather than served at their own URLs, so this script drives
the nav the way a user would, then takes a full-page screenshot of each.
Captures docs/screenshots/queue.png and analytics.png in dark mode.

Requires the API running on localhost:8000 (``uvicorn api.main:app``)
and a local Edge install (uses Playwright's channel="msedge", no browser
download).

    python scripts/capture_screenshots.py
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
WIDTH = 1440


def settle(page, seconds=1.5):
    page.wait_for_load_state("networkidle")
    time.sleep(seconds)


def show_view(page, view):
    """Click a nav link and wait for the view to render."""
    page.click(f'a[data-view="{view}"]')
    settle(page)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        # No stored theme, so the app follows prefers-color-scheme.
        context = browser.new_context(
            color_scheme="dark",
            viewport={"width": WIDTH, "height": 1100},
        )
        page = context.new_page()
        page.goto(BASE)
        settle(page)

        # --- Queue: hide unevaluated tickets so AI categories show, then
        # select a visible row so the detail panel shows a real evaluation
        # (the default selection is the newest ticket, often unevaluated).
        show_view(page, "queue")
        page.uncheck('input[data-action="cat-filter"][data-label="Not yet evaluated"]')
        settle(page)
        page.click('tr[data-action="select-row"]')
        settle(page)
        page.screenshot(path=str(OUT / "queue.png"), full_page=True)
        print("queue.png")

        # --- Analytics ---
        show_view(page, "analytics")
        page.screenshot(path=str(OUT / "analytics.png"), full_page=True)
        print("analytics.png")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
