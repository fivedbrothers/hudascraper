import os
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

# Ensure Playwright is available for integration tests; skip otherwise.
pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "test-site"


def serve(dirpath: Path, port: int = 8000):
    handler = partial(SimpleHTTPRequestHandler, directory=str(dirpath))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


@pytest.mark.integration
def test_ms_sso_flow_integration():
    """
    End-to-end MS SSO flow against the local `test-site/`.

    This test is intentionally gated behind an environment variable so it
    only runs when explicitly requested by a developer or CI job that has
    Playwright and browser binaries installed.
    """
    if os.environ.get("RUN_PLAYWRIGHT_INTEGRATION", "0") != "1":
        pytest.skip("Set RUN_PLAYWRIGHT_INTEGRATION=1 to run Playwright integrations")

    # sync_playwright is imported at module level
    srv, thread = serve(ROOT, port=8000)
    try:
        # small delay for server to be reachable
        time.sleep(0.1)
        base = "http://127.0.0.1:8000/index.html"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()

            page.goto(base, wait_until="domcontentloaded")

            # Click the app's ms-signin button
            page.click("#ms-signin")

            # Wait for ms-login page to load and fill fields
            page.wait_for_selector("input[name='loginfmt']", timeout=5000)
            page.fill("input[name='loginfmt']", "test@example.com")
            page.click("#next")

            page.wait_for_selector("#pwd", timeout=5000)
            page.fill("#pwd", "password")
            page.click("#signin")

            # Final page should be success.html
            page.wait_for_url("**/success.html", timeout=5000)
            assert "success.html" in page.url

            ctx.close()
            browser.close()
    finally:
        srv.shutdown()
