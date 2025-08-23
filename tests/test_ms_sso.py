from unittest.mock import Mock

from hudascraper.hudasconfig import Config
from hudascraper.hudascraper import MsSsoAuth


def test_ms_sso_skips_without_credentials() -> None:
    cfg = Config()
    page = Mock()
    resolver = Mock()

    auth = MsSsoAuth(username="", password="")
    # Should return quickly and not call resolver.locate
    auth.login(page, cfg, resolver)
    assert resolver.locate.call_count == 0


def test_ms_sso_fills_and_clicks_when_on_ms_host() -> None:
    # Build a config with the expected MS selector sets
    cfg = Config()
    cfg.selectors = {
        "ms_email": {"candidates": [{"selector": "#email"}]},
        "ms_next": {"candidates": [{"selector": "#next"}]},
        "ms_password": {"candidates": [{"selector": "#password"}]},
        "ms_signin": {"candidates": [{"selector": "#signin"}]},
    }

    # Fake page that starts on MS host and supports wait_for_timeout
    page = Mock()
    page.url = "https://login.microsoftonline.com/common/oauth2/v2.0/"
    page.wait_for_timeout = Mock()

    # Prepare distinct locator mocks so we can assert they were called
    email_loc = Mock()
    next_loc = Mock()
    password_loc = Mock()
    signin_loc = Mock()

    # Make signin click change the page URL to simulate redirect back to app
    def signin_click_side_effect():
        page.url = "https://app.example/after"

    signin_loc.click.side_effect = signin_click_side_effect

    # Resolver.locate should return the appropriate mock based on selector
    def fake_locate(root, selset):
        sel = selset.candidates[0].selector
        if sel == "#email":
            return email_loc
        if sel == "#next":
            return next_loc
        if sel == "#password":
            return password_loc
        if sel == "#signin":
            return signin_loc
        return Mock()

    resolver = Mock()
    resolver.locate.side_effect = fake_locate

    auth = MsSsoAuth(username="user@example.com", password="secret", timeout_s=5)

    # Run login; since page is already on MS host, it should perform fill/clicks
    auth.login(page, cfg, resolver)

    # Assert the resolver was used to locate each control and their methods were invoked
    assert resolver.locate.call_count >= 4
    # email filled
    assert email_loc.fill.called
    # next clicked
    assert next_loc.click.called
    # password filled
    assert password_loc.fill.called
    # signin clicked and resulted in page leaving MS host
    assert signin_loc.click.called
    assert "app.example" in page.url
