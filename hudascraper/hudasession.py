import json
import os
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page

from .hudasconfig import Config


def _state_file(cfg: Config) -> Path:
    if cfg.session.path:
        return cfg.session.path
    base = Path.home() / ".scraper" / "sessions"
    f = f"{cfg.session.user or 'default'}.json"
    return base / cfg.session.site_host / f


def load_context(browser: Browser, cfg: Config) -> tuple[BrowserContext, bool]:
    spath = _state_file(cfg)
    if cfg.session.reuse and spath.exists():
        try:
            return browser.new_context(storage_state=str(spath)), True
        except Exception:
            spath.rename(spath.with_suffix(".bad"))
    return browser.new_context(), False


def save_context(ctx: BrowserContext, cfg: Config) -> None:
    if not cfg.session.save_on_success:
        return
    spath = _state_file(cfg)
    spath.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=spath.parent)
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(ctx.storage_state(), f)
    os.replace(tmp_path, spath)


def is_ms_login(url: str) -> bool:
    return any(
        h in (url or "")
        for h in ["login.microsoftonline.com", "login.live.com", "login.microsoft.com"]
    )


def is_logged_in(page: Page, cfg: Config) -> bool:
    guard = cfg.selectors.get("logged_in_guard")
    if guard:
        try:
            return page.locator(guard).first.is_visible(timeout=1000)
        except Exception:
            return False
    return (not is_ms_login(page.url)) and cfg.session.site_host in (page.url or "")


def wait_until(pred, timeout_s: int, poll_ms: int = 250) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(poll_ms / 1000)
    return False
