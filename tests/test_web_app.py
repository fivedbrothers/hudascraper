import json
from unittest.mock import Mock, patch

import pytest

import hudascraper_web as web


def test_safe_json_loads_valid():
    s = '{"a": 1, "b": [1,2,3]}'
    obj = web._safe_json_loads(s)
    assert isinstance(obj, dict)
    assert obj["a"] == 1


@pytest.mark.parametrize("bad", [None, "", "{not: json}"])
def test_safe_json_loads_invalid(bad):
    with pytest.raises(ValueError):
        web._safe_json_loads(bad)


def test_post_scrape_wrapped_and_params():
    sample_cfg = {"hello": "world"}
    fake_resp = Mock()
    fake_resp.json.return_value = {"run_id": "abc123"}
    fake_resp.raise_for_status.return_value = None

    with patch("hudascraper_web.requests.post", return_value=fake_resp) as post:
        res = web._post_scrape(
            "http://example.local/",
            sample_cfg,
            wrapped=True,
            username="u",
            password="p",
        )
        assert res["run_id"] == "abc123"
        post.assert_called_once()
        called_url = (
            post.call_args[1]["url"]
            if "url" in post.call_args[1]
            else post.call_args[0][0]
        )
        assert "example.local" in called_url


def test_get_results_returns_dataframe_like():
    # Build a fake JSON response that would come from the /results endpoint
    fake_items = [{"x": 1}, {"x": 2}]
    fake_resp = Mock()
    fake_resp.json.return_value = {"items": fake_items}
    fake_resp.raise_for_status.return_value = None

    with patch("hudascraper_web.requests.get", return_value=fake_resp) as get:
        df = web._get_results("http://example.local/", "run1")
        # Expect a pandas DataFrame; at minimum it should have iterrows
        assert hasattr(df, "iterrows")
        assert len(list(df.iterrows())) == 2
