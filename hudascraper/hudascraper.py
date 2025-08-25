from __future__ import annotations

"""hudascraper.hudascraper.

Core scraper runtime and extraction primitives.
"""

import argparse
import contextlib
import logging
import re
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from .hudasconfig import (
    Config,
    SelectorCandidate,
    SelectorSet,
    load_config,
)
from .hudasession import (
    _state_file,
    is_logged_in,
    load_context,
    save_context,
    wait_until,
)

if TYPE_CHECKING:
    # typing-only imports
    from collections.abc import Callable
    # Playwright types for static analysis
    try:  # pragma: no cover - only for typing
        from playwright.sync_api import Locator, Page  # type: ignore
    except Exception:  # pragma: no cover - typing only
        Locator = object  # type: ignore
        Page = object  # type: ignore

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import Locator, Page, sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except (ImportError, ModuleNotFoundError):  # Playwright optional at import-time
    PlaywrightError = Exception  # type: ignore[attr-defined]
    PlaywrightTimeoutError = Exception  # type: ignore[attr-defined]
    Page = object  # type: ignore[attr-defined]
    Locator = object  # type: ignore[attr-defined]

    def sync_playwright() -> None:
        raise RuntimeError("playwright not available")

# duplicate imports removed

"""
Full module description (moved below imports to keep imports at module top):

- loading configuration via :class:`hudascraper.hudasconfig.Config`;
- optional pre-actions (configured navigations/clicks) to trigger login flows
    or reveal tabbed content;
- optional authentication strategies (for example, :class:`MsSsoAuth`);
- selector resolution with multiple candidate selectors and engines;
- pagination strategies (next-button, load-more, numbered, infinite scroll);
- normalization and conversion to :class:`pandas.DataFrame`.

The public contract:

- GenericScraper(cfg, auth=None).run() -> pandas.DataFrame

The code is written to be configuration-driven so the same runtime can be
reused across internal apps and public websites.

See :mod:`hudascraper.hudasconfig` for the JSON configuration structure.
"""

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
if pd is None:
    logger.debug("pandas not available; DataFrame conversion will raise if used")

UNSTABLE_PATTERNS = [
    r":nth-(child|of-type)\(",  # brittle positional CSS
    r"//.*text\(\)\s*=",  # text-based XPath
    r"^/{1,2}(?!html)",  # absolute XPaths from root (allow 'html' root narrowly)
]


# ----------------------------
# Selector resolution
# ----------------------------


class SelectorResolver:
    """
    Resolve selector candidates into Playwright Locator objects.

    The resolver accepts a :class:`SelectorSet` (an ordered list of
    :class:`SelectorCandidate`) and attempts each candidate in order until a
    matching locator is found. It performs lightweight validation against
    a set of unstable selector heuristics and provides a convenience
    ``maybe`` method that returns None instead of raising on failure.
    """

    def __init__(self, page: Page) -> None:
        self.page = page

    def _validate(self, cand: SelectorCandidate) -> None:
        if cand.allow_unstable:
            return
        for pat in UNSTABLE_PATTERNS:
            if re.search(pat, cand.selector):
                msg = f"Rejected unstable selector: {cand.selector}"
                raise ValueError(msg)

    def locate(self, root: Locator | Page, selset: SelectorSet) -> Locator:
        last_err: Exception | None = None
        for cand in selset.candidates:
            try:
                self._validate(cand)
                loc = self._loc(root, cand)

                # Wait for element — prefer waiting on the full locator when a
                # single match is expected, but if Playwright raises a strict
                # mode violation (multiple elements), fall back to waiting on
                # the first element. This handles header/cell sets that match
                # multiple nodes (e.g., multiple <th> elements).
                try:
                    if cand.multi_match:
                        loc.first.wait_for(state=cand.state, timeout=cand.timeout_ms)
                    else:
                        loc.wait_for(state=cand.state, timeout=cand.timeout_ms)
                except PlaywrightError as e:
                    # If locator resolved to multiple elements, use the first
                    # element as a pragmatic fallback and continue; re-raise
                    # for other Playwright errors.
                    msg = str(e)
                    if "strict mode violation" in msg or "resolved to" in msg:
                        loc.first.wait_for(
                            state=cand.state,
                            timeout=cand.timeout_ms,
                        )
                    else:
                        raise

            except (PlaywrightError, PlaywrightTimeoutError, ValueError) as e:
                last_err = e
                continue
            else:
                return loc

        # If we reach here no candidate matched — build a helpful diagnostic
        sel_list = [c.selector for c in selset.candidates]
        msg = f"None of the candidates matched: {sel_list} | last_error={last_err}"
        raise RuntimeError(msg)

    def maybe(self, root: Locator | Page, selset: SelectorSet) -> Locator | None:
        try:
            return self.locate(root, selset)
        except (PlaywrightError, PlaywrightTimeoutError, ValueError, RuntimeError):
            return None

    def _loc(self, root: Locator | Page, cand: SelectorCandidate) -> Locator:
        if cand.engine == "css":
            return root.locator(cand.selector)
        return root.locator(f"xpath={cand.selector}")


# ----------------------------
# Authentication hook (optional)
# ----------------------------


class AuthStrategy:
    """
    Base class for optional authentication strategies.

    Implementations should override ``login`` to perform provider-specific
    automated sign-in flows (for example Microsoft SSO). The login method
    is called with a Playwright :class:`Page`, the loaded :class:`Config`,
    and a :class:`SelectorResolver` to locate configured controls.
    """

    def login(
        self,
        _page: Page,
        _cfg: Config,
        _resolver: SelectorResolver,
    ) -> None:  # pragma: no cover
        """
        Optional hook: perform an automated login if available.

        The default implementation is a no-op. Concrete strategies should
        be resilient to partial configurations and avoid raising on
        expected site-specific variations.
        """
        return


# Microsoft SSO (selectors must be provided in config if used)
class MsSsoAuth(AuthStrategy):
    def __init__(self, username: str, password: str, timeout_s: int = 60) -> None:
        self.username = username
        self.password = password
        self.timeout_s = timeout_s

    """Automated Microsoft SSO authentication strategy.

    This implementation expects the configuration to provide selectors for
    the MS email/next/password/signin controls (see README/docs). It will
    optionally attempt to trigger an app-initiated redirect to the MS
    host (clicking a configured app-signin control) and then perform the
    email/password form submission on the identity provider.
    """

    def _on_ms_host(self, page: Page) -> bool:
        u = page.url or ""
        return any(
            h in u
            for h in (
                "login.microsoftonline.com",
                "login.live.com",
                "login.microsoft.com",
            )
        )

    def _trigger_app_signin(
        self,
        page: Page,
        cfg: Config,
        resolver: SelectorResolver,
        mk: Callable[[dict], SelectorSet],
    ) -> None:
        # Try clicking an app signin control (if configured) to start the redirect
        app_signin = cfg.selectors.get("ms_app_signin") or cfg.selectors.get(
            "ms_signin",
        )
        # Only suppress Playwright/browser related errors here so we don't hide other bugs
        with contextlib.suppress(PlaywrightError, PlaywrightTimeoutError):
            resolver.locate(page, mk(app_signin)).click()

    def _wait_for_ms_host(self, page: Page, _cfg: Config, max_wait: float) -> bool:
        deadline = monotonic() + max_wait
        while monotonic() < deadline:
            if self._on_ms_host(page):
                return True
            page.wait_for_timeout(250)
        return False

    def _fill_and_submit(
        self,
        page: Page,
        cfg: Config,
        resolver: SelectorResolver,
        mk: Callable[[dict], SelectorSet],
        left: Callable[[], float],
    ) -> None:
        # Fill email -> next -> password -> signin
        resolver.locate(page, mk(cfg.selectors.get("ms_email"))).fill(self.username)
        resolver.locate(page, mk(cfg.selectors.get("ms_next"))).click()
        resolver.locate(page, mk(cfg.selectors.get("ms_password"))).fill(self.password)
        resolver.locate(page, mk(cfg.selectors.get("ms_signin"))).click()

        # wait until page leaves MS host
        while left() > 0:
            if not self._on_ms_host(page):
                break
            page.wait_for_timeout(250)

    def login(self, page: Page, cfg: Config, resolver: SelectorResolver) -> None:
        if not (self.username and self.password):
            return
        # selectors expected for MS flow
        email = cfg.selectors.get("ms_email")
        next_btn = cfg.selectors.get("ms_next")
        pwd = cfg.selectors.get("ms_password")
        signin = cfg.selectors.get("ms_signin")
        if not all([email, next_btn, pwd, signin]):
            logger.debug(
                "MsSsoAuth.login: MS selector set incomplete, skipping automated login",
            )
            return

        def mk(ss: dict) -> SelectorSet:
            return SelectorSet([SelectorCandidate(**c) for c in ss["candidates"]])

        deadline = monotonic() + self.timeout_s

        def left() -> float:
            return max(0.0, deadline - monotonic())

        # If we're not on the MS-host yet, try to trigger the redirect from the app page
        if not self._on_ms_host(page):
            # try clicking the app sign-in control (suppress errors)
            try:
                self._trigger_app_signin(page, cfg, resolver, mk)
            except (PlaywrightError, PlaywrightTimeoutError):
                # keep going — the helper already suppresses expected exceptions
                logger.exception(
                    "MsSsoAuth: unexpected error while triggering app signin",
                )

            # allow configurable short wait for redirect via config (selectors key)
            redirect_wait = cfg.selectors.get("ms_redirect_wait_s")
            try:
                redirect_wait = (
                    float(redirect_wait)
                    if redirect_wait is not None
                    else min(self.timeout_s, 8)
                )
            except (TypeError, ValueError):
                redirect_wait = min(self.timeout_s, 8)

            if not self._wait_for_ms_host(
                page,
                cfg,
                min(self.timeout_s, redirect_wait),
            ):
                logger.debug(
                    "MsSsoAuth.login: did not reach MS host after trigger; aborting",
                )
                return

        # Now on MS host — attempt form fill/submit
        try:
            self._fill_and_submit(page, cfg, resolver, mk, left)
        except (PlaywrightError, PlaywrightTimeoutError):
            logger.exception("MsSsoAuth.login: exception during MS form fill/submit")


# ----------------------------
# Pagination strategies
# ----------------------------


class Paginator:
    """
    Abstract pagination strategy.

    Subclasses implement ``next_page`` returning True when navigation to a
    next page was issued and False when no further pages are available.
    """

    def next_page(self) -> bool:  # pragma: no cover
        """
        Advance to the next page.

        Returns True when navigation to another page/content was initiated.
        Returns False when no further pages exist.
        """
        raise NotImplementedError


class NextButtonPaginator(Paginator):
    def __init__(
        self, root: Locator | Page, resolver: SelectorResolver, btn_cfg: dict,
    ) -> None:
        self.root = root
        self.resolver = resolver
        button = btn_cfg.get("button") or {"candidates": []}
        self.btn_set = SelectorSet(
            [SelectorCandidate(**c) for c in button["candidates"]],
        )
        self.disabled_checks = btn_cfg.get(
            "disabled_checks",
            ["aria_disabled", "property_disabled"],
        )

    """Paginator that clicks a "Next" or paging control.

    The constructor expects a ``btn_cfg`` dict with a nested
    ``button.candidates`` list (same shape as selector config). The
    paginator optionally checks for disabled state via attribute or
    properties (configurable via ``disabled_checks``).
    """

    def next_page(self) -> bool:
        btn_loc = self.resolver.maybe(self.root, self.btn_set)
        if btn_loc is None:
            return False

        btn = btn_loc.first
        try:
            if "property_disabled" in self.disabled_checks and btn.evaluate(
                "el => !!el.disabled",
            ):
                return False
            if "aria_disabled" in self.disabled_checks:
                aria = btn.get_attribute("aria-disabled")
                if aria and aria.lower() == "true":
                    return False
            btn.click()
            return True
        except (PlaywrightError, PlaywrightTimeoutError):
            logger.debug("NextButtonPaginator: click/evaluate failed on button")
            return False


class LoadMorePaginator(Paginator):
    def __init__(
        self, root: Locator | Page, resolver: SelectorResolver, cfg: dict,
    ) -> None:
        self.root = root
        self.resolver = resolver
        self.btn_set = SelectorSet(
            [
                SelectorCandidate(**c)
                for c in (cfg.get("button") or {"candidates": []})["candidates"]
            ],
        )

    """Paginator that clicks a 'Load more' control to append rows.

    The configuration should provide a ``button`` selector set. If the
    button is not present the paginator reports completion.
    """

    def next_page(self) -> bool:
        btn_loc = self.resolver.maybe(self.root, self.btn_set)
        if btn_loc is None:
            return False
        try:
            btn_loc.click()
            return True
        except (PlaywrightError, PlaywrightTimeoutError):
            return False


class NumberedPaginator(Paginator):
    def __init__(
        self, root: Locator | Page, resolver: SelectorResolver, cfg: dict,
    ) -> None:
        self.root = root
        self.resolver = resolver
        container = cfg.get("container") or {"candidates": []}
        self.container_set = SelectorSet(
            [SelectorCandidate(**c) for c in container["candidates"]],
        )
        self.pattern = cfg.get("next_page_pattern", "a[aria-label='Page {n}']")
        self.n = cfg.get("start_from", 2)

    """Paginator that clicks a numbered page link.

    The config may provide a ``container`` selector to scope the page
    links, a ``next_page_pattern`` with ``{n}`` placeholder, and an
    optional ``start_from`` value.
    """

    def next_page(self) -> bool:
        container = self.resolver.maybe(self.root, self.container_set)
        if container is None:
            return False
        try:
            target = container.locator(self.pattern.format(n=self.n))
            target.wait_for(state="visible", timeout=3000)
            target.click()
            self.n += 1
            return True
        except (PlaywrightError, PlaywrightTimeoutError):
            return False


class InfiniteScrollPaginator(Paginator):
    def __init__(self, root: Locator | Page, cfg: dict) -> None:
        self.root = root
        self.scroll_step = int(cfg.get("scroll_step_px", 1200))
        self.idle_ms = int(cfg.get("idle_ms", 800))
        self.max_scrolls = int(cfg.get("max_scrolls", 50))
        self._count = 0

    """Paginator that scrolls the container to load additional content.

    The config may tune ``scroll_step_px``, ``idle_ms`` and ``max_scrolls``.
    """

    def next_page(self) -> bool:
        if self._count >= self.max_scrolls:
            return False
        try:
            self.root.evaluate(f"el => el.scrollBy(0, {self.scroll_step})")
        except (PlaywrightError, PlaywrightTimeoutError):
            try:
                self.root.page.evaluate(f"window.scrollBy(0, {self.scroll_step})")
            except (PlaywrightError, PlaywrightTimeoutError):
                logger.debug("InfiniteScrollPaginator: scroll attempt failed")
                return False
        self.root.page.wait_for_timeout(self.idle_ms)
        self._count += 1
        return True


# ----------------------------
# Extraction
# ----------------------------


class GenericExtractor:
    """
    Extract table header and row data from a page or root locator.

    The extractor is initialized with a :class:`SelectorResolver`, the
    loaded :class:`Config`, and the root :class:`Page` or :class:`Locator`
    to scope extraction (for example, an iframe locator).
    """

    def __init__(
        self,
        resolver: SelectorResolver,
        cfg: Config,
        page_or_root: Locator | Page,
    ) -> None:
        self.r = resolver
        self.cfg = cfg
        self.root = page_or_root

        sel = cfg.selectors
        self.table_container = SelectorSet(
            [SelectorCandidate(**c) for c in sel["table_container"]["candidates"]],
        )

        hdr_cfg = sel.get("header_cells")
        self.header_cells = (
            SelectorSet([SelectorCandidate(**c) for c in hdr_cfg["candidates"]])
            if hdr_cfg
            else None
        )

        self.row = SelectorSet(
            [SelectorCandidate(**c) for c in sel["row"]["candidates"]],
        )
        self.cell = SelectorSet(
            [SelectorCandidate(**c) for c in sel["cell"]["candidates"]],
        )

    def read_page(self) -> tuple[list[str] | None, list[list[str]]]:
        """
        Read header (optional) and rows from the configured table.

        Returns a tuple ``(headers, rows)`` where ``headers`` is either a
        list of column names or None when no header could be resolved.
        ``rows`` is a list of lists of cell strings.
        """
        container = self.r.locate(self.root, self.table_container)

        # Header
        headers: list[str] | None = None
        if self.header_cells:
            try:
                header_loc = self.r.locate(container, self.header_cells)
                header_texts = header_loc.all_inner_texts()
                headers = [self._norm(t) for t in header_texts if t is not None]
                if all(not h for h in headers):
                    headers = None
            except (PlaywrightError, PlaywrightTimeoutError, ValueError):
                headers = None

        # Rows and cells
        row_loc = self.r.locate(container, self.row)
        rows: list[list[str]] = []
        count = row_loc.count()
        for i in range(count):
            r = row_loc.nth(i)
            # Resolve cells relative to row; use first candidate engine/selector
            cell_cands = self.cell.candidates
            if not cell_cands:
                texts = []
            else:
                first = cell_cands[0]
                cells_loc = (
                    r.locator(first.selector)
                    if first.engine == "css"
                    else r.locator(f"xpath={first.selector}")
                )
                texts = cells_loc.all_inner_texts()
            rows.append([self._norm(t) for t in texts])

        return headers, rows

    def _norm(self, s: str) -> str:
        s = s or ""
        norm = self.cfg.data_normalization
        if norm.get("trim_whitespace", True):
            s = s.strip()
        if norm.get("collapse_spaces", True):
            s = re.sub(r"\s+", " ", s)
        return s


# ----------------------------
# Scraper runtime
# ----------------------------


class GenericScraper:
    """
    Orchestrates a single scraping run using a :class:`Config`.

    Responsibilities:

    - manage Playwright lifecycle (browser, context, page)
    - reuse or persist storage_state per :class:`SessionConfig`
    - run configured ``pre_actions`` to trigger UI flows
    - optionally perform automated login via an :class:`AuthStrategy`
    - prepare the page (frames, waits, hide spinners)
    - paginate and extract rows
    - convert results to :class:`pandas.DataFrame`.
    """

    def __init__(self, cfg: Config, auth: AuthStrategy | None = None) -> None:
        self.cfg = cfg
        self.auth = auth
        self._play = sync_playwright().start()

        # Determine whether a saved storage state exists so we can optionally
        # force a headed (visible) browser on the first run when requested.
        state_path = _state_file(cfg)
        session_exists = bool(cfg.session.reuse and state_path.exists())

        headless_effective = cfg.headless
        if not session_exists and cfg.session.headed_on_first_run:
            # Force headed browser on first run so a user can complete MFA/manual login
            headless_effective = False
            logger.info(
                "GenericScraper: no session found and headed_on_first_run=True,",
            )

        browser_type = getattr(self._play, cfg.browser)
        browser = browser_type.launch(headless=headless_effective)

        self.context, self._state_reused = load_context(browser, cfg)

        self.page: Page = self.context.new_page()

    def close(self) -> None:
        """Shut down Playwright browser context and stop the driver."""
        try:
            self.context.close()
        finally:
            self._play.stop()

    def _ensure_authenticated(self) -> None:
        """
        Ensure the runtime has an authenticated session.

        Steps:
        - navigate to base URL
        - execute any ``pre_actions`` from the config (clicks/fills/navigates)
        - if no reusable state was loaded and the page is not logged in,
          invoke the configured :class:`AuthStrategy` (if any) and wait for
          the post-login guard.
        - on success, persist storage_state for future runs.
        """
        self.page.goto(self.cfg.base_url, wait_until="domcontentloaded")
        resolver = SelectorResolver(self.page)

        # Execute any configured pre_actions (app-specific navigation to trigger
        # authentication flows or reveal content). Actions are small and simple
        # to keep configs expressive and avoid embedding site-specific clicks
        # inside auth strategy implementations.
        for act in self.cfg.pre_actions or []:
            try:
                a = act.get("action")
                sel = act.get("selector")
                val = act.get("value")
                if a == "navigate":
                    target = val or sel or self.cfg.base_url
                    self.page.goto(
                        target,
                        wait_until="domcontentloaded",
                    )
                    continue
                if not sel:
                    continue
                selset = SelectorSet(
                    [
                        SelectorCandidate(**c)
                        for c in {"candidates": [{"selector": sel}]}.get("candidates")
                    ],
                )
                loc = resolver.maybe(self.page, selset)
                if loc is None:
                    continue
                if a == "click":
                    loc.first.click()
                elif a == "fill" and val is not None:
                    loc.fill(val)
                elif a == "select" and val is not None:
                    # Select option for <select> controls
                    try:
                        loc.select_option(str(val))
                    except (
                        PlaywrightError,
                        PlaywrightTimeoutError,
                        TypeError,
                        ValueError,
                    ):
                        # fallback to click+fill for custom controls
                        loc.click()
                        loc.fill(str(val))
                # small pause between actions
                self.page.wait_for_timeout(int(act.get("pause_ms", 150)))
            except (
                PlaywrightError,
                PlaywrightTimeoutError,
                ValueError,
                TypeError,
            ) as exc:
                # Log pre-action errors but continue; leave auth flow to surface
                # eventual failures. Avoid silently swallowing all exceptions.
                logger.debug("pre_action failed: %s", exc)
                continue

        if not self._state_reused and not is_logged_in(self.page, self.cfg):
            # trigger whatever login strategy is in use
            if self.auth:
                self.auth.login(self.page, self.cfg, resolver)

            # wait for post-login condition
            wait_until(
                lambda: is_logged_in(self.page, self.cfg),
                self.cfg.session.auth_timeout_s,
            )

            # save successful state for next run
            if is_logged_in(self.page, self.cfg):
                save_context(self.context, self.cfg)

    def _enter_frames(self) -> Locator | Page:
        """
        Return the locator scoped inside configured frames (if any).

        The function iterates over configured frames and updates the root
        locator to the matching frame locator. If no frames are configured
        the page is returned (top-level context).
        """
        root: Locator | Page = self.page
        for f in self.cfg.frames or []:
            if s := f.get("url_substring"):
                fl = self.page.frame_locator(f"iframe[src*='{s}']")
                fl.first.wait_for()
                root = fl.first
            elif cand := f.get("selector"):
                fl = self.page.frame_locator(cand)
                fl.first.wait_for()
                root = fl.first
        return root

    def _wait_ready(self, resolver: SelectorResolver, root: Locator | Page) -> None:
        """
        Wait for one of the configured readiness targets and hide spinners.

        The method first waits for any ``wait_targets`` to be present, then
        attempts to resolve ``spinners_to_hide`` selectors (useful when a
        page shows transient overlays).
        """
        # Wait until any of the wait_targets resolves
        for target in self.cfg.wait_targets or []:
            try:
                sel = SelectorSet([SelectorCandidate(**target)])
                resolver.locate(root, sel)
                break
            except (PlaywrightError, PlaywrightTimeoutError, ValueError):
                continue
        # Hide/await spinners/overlays if provided
        for sp in self.cfg.spinners_to_hide or []:
            try:
                sel = SelectorSet([SelectorCandidate(**sp)])
                resolver.locate(root, sel)  # e.g., state: hidden
            except (PlaywrightError, PlaywrightTimeoutError, ValueError):
                pass

    def _set_rows_per_page(
        self, resolver: SelectorResolver, root: Locator | Page,
    ) -> None:
        cfg = self.cfg.rows_per_page or {}
        if not cfg:
            return
        val = str(cfg.get("value", 100))
        control_cfg = cfg.get("control")
        if not control_cfg:
            return
        try:
            control = resolver.locate(
                root,
                SelectorSet(
                    [SelectorCandidate(**c) for c in control_cfg["candidates"]],
                ),
            )
            tag = (
                control.evaluate("el => el.tagName && el.tagName.toLowerCase()") or ""
            ).lower()
            if tag == "select":
                control.select_option(val)
            else:
                control.click()
                control.fill(val)
                control.press("Enter")
        except (PlaywrightError, PlaywrightTimeoutError):
            pass

    def _make_paginator(
        self,
        resolver: SelectorResolver,
        root: Locator | Page,
    ) -> Paginator:
        pc = self.cfg.pagination
        if not pc:
            return NextButtonPaginator(
                root,
                resolver,
                {"button": {"candidates": []}},
            )
        if pc.strategy == "next_button":
            return NextButtonPaginator(
                root,
                resolver,
                pc.next_button or {"button": {"candidates": []}},
            )
        if pc.strategy == "load_more":
            return LoadMorePaginator(
                root,
                resolver,
                pc.load_more or {"button": {"candidates": []}},
            )
        if pc.strategy == "numbered":
            return NumberedPaginator(root, resolver, pc.numbered or {})
        if pc.strategy == "infinite_scroll":
            return InfiniteScrollPaginator(root, pc.infinite_scroll or {})
        msg = f"Unknown pagination strategy: {pc.strategy}"
        raise ValueError(msg)

    def run(self) -> pd.DataFrame:
        """
        Execute the configured scraping run and return a DataFrame.

        The method ensures authentication, locates the table container,
        iterates pages using the configured paginator, reads rows and
        optionally applies deduplication, max_rows/pages limits, and
        returns a :class:`pandas.DataFrame` with ``page_count`` attribute
        set to the number of pages processed.
        """
        self._ensure_authenticated()

        resolver = SelectorResolver(self.page)
        root = self._enter_frames()
        self._wait_ready(resolver, root)
        self._set_rows_per_page(resolver, root)

        extractor = GenericExtractor(resolver, self.cfg, root)
        # Defensive wait: some pages (or session-restored contexts) may need
        # a brief moment before the expected table container appears. Allow a
        # short configurable wait and one navigate retry to reduce flakiness in
        # integration tests and real runs.
        table_found = False
        try:
            wait_for_table_s = int(
                self.cfg.data_normalization.get("wait_for_table_s", 3) or 3,
            )
        except (TypeError, ValueError):
            wait_for_table_s = 3

        deadline = monotonic() + wait_for_table_s
        while monotonic() < deadline:
            if resolver.maybe(root, extractor.table_container) is not None:
                table_found = True
                break
            self.page.wait_for_timeout(250)

        if not table_found:
            # Try navigating to the configured base_url once and retry briefly.
            # Only suppress Playwright navigation errors here.
            with contextlib.suppress(PlaywrightError, PlaywrightTimeoutError):
                self.page.goto(self.cfg.base_url, wait_until="domcontentloaded")

            deadline2 = monotonic() + 2.0
            while monotonic() < deadline2:
                if resolver.maybe(root, extractor.table_container) is not None:
                    table_found = True
                    break
                self.page.wait_for_timeout(200)

        if not table_found:
            # Provide a clearer diagnostic to help tests and developers debug
            # missing selector issues without changing existing behavior.
            try:
                page_content = (self.page.content() or "")[:2000]
            except (PlaywrightError, PlaywrightTimeoutError):
                page_content = "<unavailable>"
            sel = None
            try:
                sel = extractor.table_container.candidates[0].selector
            except (IndexError, AttributeError):
                sel = str(extractor.table_container)
            msg = f"Table container {sel!r} not found on page {self.page.url!r}. Page content head: {page_content!r}"
            raise RuntimeError(msg)

        paginator = self._make_paginator(resolver, root)

        all_rows: list[list[str]] = []
        header: list[str] | None = None
        max_pages = int(self.cfg.data_normalization.get("max_pages", 0) or 0)
        max_rows = int(self.cfg.data_normalization.get("max_rows", 0) or 0)
        dedupe = bool(self.cfg.data_normalization.get("dedupe_rows", True))
        seen = set()

        page_i = 0
        while True:
            page_i += 1
            h, rows = extractor.read_page()
            if header is None and h:
                header = h

            for r in rows:
                tup = tuple(r)
                if dedupe:
                    if tup in seen:
                        continue
                    seen.add(tup)
                all_rows.append(r)
                if max_rows and len(all_rows) >= max_rows:
                    break

            if (max_pages and page_i >= max_pages) or (
                max_rows and len(all_rows) >= max_rows
            ):
                break

            if not paginator.next_page():
                break

            # Small pause to allow DOM to update between pages
            self.page.wait_for_timeout(250)

        dframe = self._to_dataframe(all_rows, header)
        dframe.attrs["page_count"] = page_i
        return dframe

    @staticmethod
    def _to_dataframe(rows: list[list[str]], header: list[str] | None) -> pd.DataFrame:
        # Use top-level `pd` imported earlier; raise a clear error if missing.
        if pd is None:
            raise RuntimeError(
                "pandas is required to convert scraped rows to a DataFrame: install pandas",
            )

        if not rows:
            return pd.DataFrame()
        max_len = max(len(r) for r in rows)
        norm = [
            r + [""] * (max_len - len(r)) if len(r) < max_len else r[:max_len]
            for r in rows
        ]
        if header and len(header) == max_len:
            cols = [c if c else f"col_{i}" for i, c in enumerate(header)]
            return pd.DataFrame(norm, columns=cols)
        return pd.DataFrame(norm, columns=[f"col_{i}" for i in range(max_len)])


# ----------------------------
# CLI
# ----------------------------


def main() -> None:
    """
    CLI entrypoint for running the scraper from the command line.

    Example:
    python -m hudascraper.hudascraper --cfg config.json --csv out.csv

    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", type=str, required=True, help="Path to selectors JSON")
    ap.add_argument("--csv", type=str, default="", help="Optional path to export CSV")
    ap.add_argument("--usr", help="Session username (for session keying)")
    ap.add_argument("--ms-username")
    ap.add_argument("--ms-password")
    args = ap.parse_args()

    cfg = load_config(args.cfg)

    if args.usr:
        cfg.session.user = args.usr

    auth = None
    if args.ms_username and args.ms_password:
        auth = MsSsoAuth(args.ms_username, args.ms_password)

    scraper = GenericScraper(cfg=cfg, auth=auth)

    try:
        dframe = scraper.run()
    finally:
        scraper.close()

    logger.info(
        "Rows: %s | Cols: %s | Pages: %s",
        len(dframe),
        len(dframe.columns),
        dframe.attrs.get("page_count"),
    )
    logger.info("\n%s", dframe.head(10).to_string(index=False))

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        dframe.to_csv(out, index=False, encoding="utf-8")
    logger.info("Saved CSV to: %s", out)


if __name__ == "__main__":
    main()
