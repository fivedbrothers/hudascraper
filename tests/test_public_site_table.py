import pytest

from hudascraper.hudasconfig import load_config
from hudascraper.hudascraper import GenericScraper


@pytest.mark.integration
def test_w3schools_table_quick():
    """
    Quick smoke test that scrapes a simple public HTML table from W3Schools.
    Gated by the integration marker because it requires Playwright/network.
    """
    cfg = load_config("config-testsite-ms.json")
    # Replace base_url to a stable public page with a simple table
    cfg.base_url = "https://www.w3schools.com/html/html_tables.asp"
    # Keep headless and avoid session reuse
    cfg.headless = True
    if getattr(cfg, "session", None) is not None:
        cfg.session.reuse = False
        cfg.session.headed_on_first_run = False

    # Table container selector for W3Schools sample table
    cfg.selectors["table_container"] = {
        "candidates": [{"selector": "#customers", "engine": "css"}],
    }
    cfg.selectors["header_cells"] = {
        "candidates": [{"selector": "thead th, tbody tr th", "engine": "css"}],
    }
    cfg.selectors["row"] = {"candidates": [{"selector": "tbody tr", "engine": "css"}]}
    cfg.selectors["cell"] = {"candidates": [{"selector": "td, th", "engine": "css"}]}

    scraper = GenericScraper(cfg, auth=None)
    try:
        df = scraper.run()
        assert hasattr(df, "iterrows")
        assert len(df) > 0
    finally:
        scraper.close()
