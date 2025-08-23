import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page
from playwright.sync_api import Error as PlaywrightError

from .hudasconfig import Config

logger = logging.getLogger(__name__)


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
        except (PlaywrightError, OSError) as e:
            # Corrupt storage state — mark and continue with fresh context
            # Only suppress OS-related errors when renaming a corrupt state file
            with contextlib.suppress(OSError):
                spath.rename(spath.with_suffix(".bad"))
            logger.exception("Failed to load storage_state, starting fresh context")
    return browser.new_context(), False


def save_context(ctx: BrowserContext, cfg: Config) -> None:
    if not cfg.session.save_on_success:
        return
    spath = _state_file(cfg)
    spath.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=spath.parent)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(ctx.storage_state(), f)
    except (OSError, TypeError) as e:
        # On I/O errors or serialization problems ensure the temp fd is closed
        with contextlib.suppress(OSError):
            os.close(tmp_fd)
        raise
    Path(tmp_path).replace(spath)


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
        except PlaywrightError:
            return False
    return (not is_ms_login(page.url)) and cfg.session.site_host in (page.url or "")


def wait_until(pred: Callable[[], bool], timeout_s: int, poll_ms: int = 250) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if pred():
                return True
        except Exception:
            # Log unexpected errors during predicate evaluation, but continue polling
            logger.debug("wait_until: predicate raised an exception")
        time.sleep(poll_ms / 1000)
    return False
