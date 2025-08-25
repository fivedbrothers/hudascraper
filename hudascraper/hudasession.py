"""
hudascraper.hudasession.

Utilities for persisting and restoring Playwright ``storage_state`` files
and simple helpers used to detect whether a page appears to be an
authenticated application view.

Helpers
-------
- _state_file(cfg): return the expected storage_state Path for a given
    :class:`hudascraper.hudasconfig.Config`.
- load_context(browser, cfg): attempt to create a new browser context
    using a saved storage_state if present.
- save_context(ctx, cfg): persist a BrowserContext's storage_state to
    disk (atomic via temporary file + replace).
- is_ms_login(url): heuristic to detect Microsoft identity provider URLs.
- is_logged_in(page, cfg): quick guard to detect logged-in state using
    either a configured guard selector or heuristics.
- wait_until(pred, timeout_s): simple polling helper used by auth flows.
"""

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
    """
    Return the path where storage_state for ``cfg`` should be stored.

    If ``cfg.session.path`` is provided it is returned verbatim. Otherwise
    a canonical location under the user's home directory is used. The
    filename is ``{user or 'default'}.json`` and the file is placed under
    ``~/.scraper/sessions/{site_host}/``.
    """
    if cfg.session.path:
        return cfg.session.path
    base = Path.home() / ".scraper" / "sessions"
    f = f"{cfg.session.user or 'default'}.json"
    return base / cfg.session.site_host / f


def load_context(browser: Browser, cfg: Config) -> tuple[BrowserContext, bool]:
    """
    Attempt to open a browser context using the saved storage state.

    Returns a tuple of ``(context, reused_flag)`` where ``reused_flag`` is
    True when an existing storage state file was successfully loaded.
    Corrupt or unreadable state files are renamed with the ``.bad`` suffix
    and a fresh context is returned.
    """
    spath = _state_file(cfg)
    if cfg.session.reuse and spath.exists():
        try:
            return browser.new_context(storage_state=str(spath)), True
        except (PlaywrightError, OSError):
            # Corrupt storage state — mark and continue with fresh context
            # Only suppress OS-related errors when renaming a corrupt state file
            with contextlib.suppress(OSError):
                spath.rename(spath.with_suffix(".bad"))
            logger.exception("Failed to load storage_state, starting fresh context")
    return browser.new_context(), False


def save_context(ctx: BrowserContext, cfg: Config) -> None:
    """
    Persist the BrowserContext storage_state to disk atomically.

    If ``cfg.session.save_on_success`` is False the function is a no-op.
    The state is written to a temporary file and then replaced to avoid
    producing partial files on interruption.
    """
    if not cfg.session.save_on_success:
        return
    spath = _state_file(cfg)
    spath.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=spath.parent)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(ctx.storage_state(), f)
    except (OSError, TypeError):
        # On I/O errors or serialization problems ensure the temp fd is closed
        with contextlib.suppress(OSError):
            os.close(tmp_fd)
        raise
    Path(tmp_path).replace(spath)


def is_ms_login(url: str) -> bool:
    """
    Return True when ``url`` appears to be a Microsoft identity page.

    This is a small heuristic used by auth flows to detect when a
    navigation has landed on an external identity provider.
    """
    return any(
        h in (url or "")
        for h in ["login.microsoftonline.com", "login.live.com", "login.microsoft.com"]
    )


def is_logged_in(page: Page, cfg: Config) -> bool:
    """
    Best-effort check that a Page represents an authenticated view.

    If the configuration provides a ``logged_in_guard`` selector it will
    be used. Otherwise a heuristic is applied: the current URL should not
    be an MS login URL and should contain the configured site host.
    """
    guard = cfg.selectors.get("logged_in_guard")
    if guard:
        try:
            return page.locator(guard).first.is_visible(timeout=1000)
        except PlaywrightError:
            return False
    return (not is_ms_login(page.url)) and cfg.session.site_host in (page.url or "")


def wait_until(pred: Callable[[], bool], timeout_s: int, poll_ms: int = 250) -> bool:
    """
    Poll ``pred`` until it returns True or ``timeout_s`` elapses.

    The predicate is executed repeatedly with a delay of ``poll_ms``
    milliseconds between attempts. Exceptions raised by ``pred`` are
    logged at the debug level and treated as a False result.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if pred():
                return True
        except Exception as exc:  # noqa: BLE001 - deliberate: predicate functions may raise transient errors
            # Log unexpected errors during predicate evaluation, but continue polling
            logger.debug("wait_until: predicate raised an exception: %s", exc)
        time.sleep(poll_ms / 1000)
    return False
