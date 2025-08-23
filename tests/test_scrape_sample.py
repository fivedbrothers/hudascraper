from pathlib import Path

import pytest

from hudascraper.hudasconfig import load_config
from hudascraper.hudascraper import GenericScraper


@pytest.mark.integration
def test_scrape_sample_headless_quick():
    """
    Run the `config-sample.json` scraper quickly in headless mode.

    This is a slow-ish integration test (starts Playwright browsers). It
    forces headless execution and disables session reuse so it is safe to run
    in CI-like environments.
    """
    repo_root = Path(__file__).resolve().parent.parent
    cfg_path = repo_root / "config-sample.json"
    assert cfg_path.exists(), "config-sample.json must exist in repo root"

    cfg = load_config(str(cfg_path))

    # Force headless, no manual-headed first run, and don't reuse sessions
    cfg.headless = True
    if getattr(cfg, "session", None) is not None:
        cfg.session.headed_on_first_run = False
        cfg.session.reuse = False

    # Keep the run short to make the test faster
    cfg.data_normalization["max_pages"] = 2
    cfg.data_normalization["max_rows"] = 0

    scraper = GenericScraper(cfg, auth=None)
    try:
        df = scraper.run()
        # Basic assertions about the returned DataFrame-like object
        assert df is not None
        assert hasattr(df, "iterrows")
        assert len(df) >= 0
    finally:
        scraper.close()
