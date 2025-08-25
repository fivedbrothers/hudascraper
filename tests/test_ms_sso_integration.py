import contextlib
import json
import os
import tempfile
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from hudascraper.hudasconfig import load_config
from hudascraper.hudascraper import GenericScraper

ROOT = Path(__file__).resolve().parents[1] / "test-site"


def serve(dirpath: Path, port: int = 8000):
    handler = partial(SimpleHTTPRequestHandler, directory=str(dirpath))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)

    thread = __import__("threading").Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


@pytest.mark.integration
def test_generic_scraper_sso_local():
    # Gate heavy Playwright test behind an env var
    if os.environ.get("RUN_PLAYWRIGHT_INTEGRATION", "0") != "1":
        pytest.skip("Set RUN_PLAYWRIGHT_INTEGRATION=1 to run Playwright integrations")

    srv, thread = serve(ROOT, port=8000)
    try:
        # small delay for server to be reachable
        time.sleep(0.1)

        cfg_path = Path(__file__).resolve().parent.parent / "config-testsite-ms.json"
        cfg = load_config(str(cfg_path))
        # After pre-login we will navigate directly to the post-login success
        # page which contains the table we want to scrape.
        cfg.base_url = "http://127.0.0.1:8000/success.html"

        # Perform login via Playwright to simulate an authenticated session
        base = "http://127.0.0.1:8000/index.html"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.click("#ms-signin")
            page.wait_for_selector("input[name='loginfmt']", timeout=5000)
            page.fill("input[name='loginfmt']", "test@example.com")
            page.click("#next")
            page.wait_for_selector("#pwd", timeout=5000)
            page.fill("#pwd", "password")
            page.click("#signin")
            page.wait_for_url("**/success.html", timeout=5000)

            # Save storage state to a temp file and configure the scraper to reuse it
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(ctx.storage_state(), f)
                cfg.session.path = Path(tmp_path)
                cfg.session.reuse = True
            finally:
                ctx.close()
                browser.close()

        # Ensure headless for CI
        cfg.headless = True

        # Run scraper without automated MsSsoAuth since session is already authenticated
        scraper = GenericScraper(cfg, auth=None)
        try:
            result = scraper.run()
            # Expect three rows from the test-site table
            assert len(result) == 3
            assert "Name" in result.columns or "col_0" in result.columns
        finally:
            # Closing Playwright contexts can occasionally raise protocol errors
            # if the browser process has already terminated. Suppress those in
            # test teardown so we don't obscure the actual test result.
            with contextlib.suppress(Exception):
                scraper.close()
    finally:
        srv.shutdown()
