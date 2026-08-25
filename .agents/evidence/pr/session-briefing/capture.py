#!/usr/bin/env python3
"""Render a recorded trace and capture the session-briefing banner.

Usage:
    uv run python .agents/evidence/pr/session-briefing/capture.py \
        .traces/cache-invalidation-diagnostics/trace_cache_diagnostics.jsonl \
        trace-viewer-session-briefing-cache.png
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from claude_tap.viewer import _generate_html_viewer  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2

    trace_path = Path(argv[1]).resolve()
    out_name = argv[2]
    if not trace_path.exists():
        print(f"trace not found: {trace_path}")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "briefing.html"
        _generate_html_viewer(trace_path, html_path)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(html_path.as_uri(), wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#session-briefing.is-visible", timeout=10000)
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT_DIR / out_name))
            print(page.locator("#session-briefing").inner_text())
            print(f"page errors: {errors}")
            browser.close()

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
