"""
A robust, generic table scraper driven by a JSON configuration file.

Key features:
- JSON-configured selectors with ordered fallbacks and multiple locator engines (CSS, XPath).
- Selector reliability guard: rejects unstable patterns unless explicitly allowed.
- Multiple pagination strategies: next_button, load_more, numbered, infinite_scroll.
- Frames support via URL substring or selector.
- Resilient waits, spinner/overlay suppression, optional rows-per-page control.
- Clean DataFrame output with header detection and normalization options.

Returned structure:
- pandas.DataFrame with .attrs["page_count"] = int

Run:
  python generic_scraper.py --config selectors.json

Requires:
  pip install playwright pandas
  playwright install
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Literal

import pandas as pd
from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PwTimeout,
)

UNSTABLE_PATTERNS = [
    r":nth-(child|of-type)\(",  # brittle positional CSS
    r"//.*text\(\)\s*=",        # text-based XPath
    r"^/{1,2}(?!html)",         # absolute XPaths from root (allow 'html' root narrowly)
]

@dataclass
class SelectorCandidate:
    selector: str
    engine: Literal["css", "xpath"] = "css"
    state: Literal["attached", "visible", "hidden"] = "attached"
    timeout_ms: int = 10000
    allow_unstable: bool = False
    multi_match: bool = False
    strict: bool = True  # TODO(Mark Dasco): implement handling of this data

@dataclass
class SelectorSet:
    candidates: list[SelectorCandidate]

@dataclass
class PaginationConfig:
    strategy: Literal["next_button", "load_more", "numbered", "infinite_scroll"] = "next_button"
    next_button: dict | None = None
    load_more: dict | None = None
    numbered: dict | None = None
    infinite_scroll: dict | None = None

@dataclass
class Config:
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    base_url: str = ""
    storage_state_path: str | None = None

    frames: list[dict] = field(default_factory=list)
    wait_targets: list[dict] = field(default_factory=list)
    spinners_to_hide: list[dict] = field(default_factory=list)

    selectors: dict = field(default_factory=dict)
    rows_per_page: dict = field(default_factory=dict)
    pagination: PaginationConfig | None = None

    header_strategy: dict = field(default_factory=dict)
    data_normalization: dict = field(default_factory=dict)

# ----------------------------
# Selector resolution
# ----------------------------

class SelectorResolver:
    def __init__(self, page: Page):
        self.page = page

    def _validate(self, cand: SelectorCandidate):
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

                # Wait for element — use .first if multi_match is expected
                if cand.multi_match:
                    loc.first.wait_for(state=cand.state, timeout=cand.timeout_ms)
                else:
                    loc.wait_for(state=cand.state, timeout=cand.timeout_ms)

            except Exception as e:
                last_err = e
                continue
            else:
                return loc

        msg = f"None of the candidates matched: {[c.selector for c in selset.candidates]} | last_error={last_err}"
        raise RuntimeError(
            msg,
        )

    def maybe(self, root: Locator | Page, selset: SelectorSet) -> Locator | None:
        try:
            return self.locate(root, selset)
        except Exception:
            return None

    def _loc(self, root: Locator | Page, cand: SelectorCandidate) -> Locator:
        if cand.engine == "css":
            return root.locator(cand.selector)
        return root.locator(f"xpath={cand.selector}")

# ----------------------------
# Authentication hook (optional)
# ----------------------------

class AuthStrategy:
    def login(self, page: Page, cfg: Config, resolver: SelectorResolver):  # pragma: no cover
        return

# Example: Microsoft SSO (selectors must be provided in config if used)
class MsSsoAuth(AuthStrategy):
    def __init__(self, username: str, password: str, timeout_s: int = 60):
        self.username = username
        self.password = password
        self.timeout_s = timeout_s

    def login(self, page: Page, cfg: Config, resolver: SelectorResolver):
        if not (self.username and self.password):
            return
        if "login.microsoftonline.com" not in (page.url or "") and "login.live.com" not in (page.url or ""):
            return

        email = cfg.selectors.get("ms_email")
        next_btn = cfg.selectors.get("ms_next")
        pwd = cfg.selectors.get("ms_password")
        signin = cfg.selectors.get("ms_signin")
        if not all([email, next_btn, pwd, signin]):
            return

        def mk(ss: dict) -> SelectorSet:
            return SelectorSet([SelectorCandidate(**c) for c in ss["candidates"]])

        deadline = monotonic() + self.timeout_s
        def left(): return max(0.0, deadline - monotonic())

        try:
            resolver.locate(page, mk(email)).fill(self.username)
            resolver.locate(page, mk(next_btn)).click()
            resolver.locate(page, mk(pwd)).fill(self.password)
            resolver.locate(page, mk(signin)).click()

            while left() > 0:
                if "login.microsoftonline.com" not in page.url and "login.live.com" not in page.url:
                    break
                page.wait_for_timeout(250)
        except Exception:
            pass

# ----------------------------
# Pagination strategies
# ----------------------------

class Paginator:
    def next_page(self) -> bool:  # pragma: no cover
        raise NotImplementedError

class NextButtonPaginator(Paginator):
    def __init__(self, root: Locator | Page, resolver: SelectorResolver, btn_cfg: dict):
        self.root = root
        self.resolver = resolver
        button = btn_cfg.get("button") or {"candidates": []}
        self.btn_set = SelectorSet([SelectorCandidate(**c) for c in button["candidates"]])
        self.disabled_checks = btn_cfg.get("disabled_checks", ["aria_disabled", "property_disabled"])

    def next_page(self) -> bool:
        try:
            btn = self.resolver.locate(self.root, self.btn_set).first
        except Exception:
            return False

        try:
            if "property_disabled" in self.disabled_checks:
                if btn.evaluate("el => !!el.disabled"):
                    return False
            if "aria_disabled" in self.disabled_checks:
                aria = btn.get_attribute("aria-disabled")
                if aria and aria.lower() == "true":
                    return False
            btn.click()
            return True
        except Exception:
            return False

class LoadMorePaginator(Paginator):
    def __init__(self, root: Locator | Page, resolver: SelectorResolver, cfg: dict):
        self.root = root
        self.resolver = resolver
        self.btn_set = SelectorSet([SelectorCandidate(**c) for c in (cfg.get("button") or {"candidates": []})["candidates"]])

    def next_page(self) -> bool:
        try:
            btn = self.resolver.locate(self.root, self.btn_set)
            btn.click()
            return True
        except Exception:
            return False

class NumberedPaginator(Paginator):
    def __init__(self, root: Locator | Page, resolver: SelectorResolver, cfg: dict):
        self.root = root
        self.resolver = resolver
        container = cfg.get("container") or {"candidates": []}
        self.container_set = SelectorSet([SelectorCandidate(**c) for c in container["candidates"]])
        self.pattern = cfg.get("next_page_pattern", "a[aria-label='Page {n}']")
        self.n = cfg.get("start_from", 2)

    def next_page(self) -> bool:
        try:
            container = self.resolver.locate(self.root, self.container_set)
            target = container.locator(self.pattern.format(n=self.n))
            target.wait_for(state="visible", timeout=3000)
            target.click()
            self.n += 1
            return True
        except Exception:
            return False

class InfiniteScrollPaginator(Paginator):
    def __init__(self, root: Locator | Page, cfg: dict):
        self.root = root
        self.scroll_step = int(cfg.get("scroll_step_px", 1200))
        self.idle_ms = int(cfg.get("idle_ms", 800))
        self.max_scrolls = int(cfg.get("max_scrolls", 50))
        self._count = 0

    def next_page(self) -> bool:
        if self._count >= self.max_scrolls:
            return False
        try:
            self.root.evaluate(f"el => el.scrollBy(0, {self.scroll_step})")
        except Exception:
            self.root.page.evaluate(f"window.scrollBy(0, {self.scroll_step})")
        self.root.page.wait_for_timeout(self.idle_ms)
        self._count += 1
        return True

# ----------------------------
# Extraction
# ----------------------------

class GenericExtractor:
    def __init__(self, resolver: SelectorResolver, cfg: Config, page_or_root: Locator | Page):
        self.r = resolver
        self.cfg = cfg
        self.root = page_or_root

        sel = cfg.selectors
        self.table_container = SelectorSet([SelectorCandidate(**c) for c in sel["table_container"]["candidates"]])

        hdr_cfg = sel.get("header_cells")
        self.header_cells = SelectorSet([SelectorCandidate(**c) for c in hdr_cfg["candidates"]]) if hdr_cfg else None

        self.row = SelectorSet([SelectorCandidate(**c) for c in sel["row"]["candidates"]])
        self.cell = SelectorSet([SelectorCandidate(**c) for c in sel["cell"]["candidates"]])

    def read_page(self) -> tuple[list[str] | None, list[list[str]]]:
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
            except Exception:
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
                cells_loc = (r.locator(first.selector) if first.engine == "css"
                             else r.locator(f"xpath={first.selector}"))
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
    def __init__(self, cfg: Config, auth: AuthStrategy | None = None):
        self.cfg = cfg
        self.auth = auth
        self._play = sync_playwright().start()

        browser_type = getattr(self._play, cfg.browser)
        browser = browser_type.launch(headless=cfg.headless)
        if cfg.storage_state_path:
            context = browser.new_context(storage_state=cfg.storage_state_path)
        else:
            context = browser.new_context()
        self.context: BrowserContext = context
        self.page: Page = context.new_page()

    def close(self):
        try:
            self.context.close()
        finally:
            self._play.stop()

    def _enter_frames(self, resolver: SelectorResolver) -> Locator | Page:
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

    def _wait_ready(self, resolver: SelectorResolver, root: Locator | Page):
        # Wait until any of the wait_targets resolves
        for target in self.cfg.wait_targets or []:
            try:
                sel = SelectorSet([SelectorCandidate(**target)])
                resolver.locate(root, sel)
                break
            except Exception:
                continue
        # Hide/await spinners/overlays if provided
        for sp in self.cfg.spinners_to_hide or []:
            try:
                sel = SelectorSet([SelectorCandidate(**sp)])
                resolver.locate(root, sel)  # e.g., state: hidden
            except Exception:
                pass

    def _set_rows_per_page(self, resolver: SelectorResolver, root: Locator | Page):
        cfg = self.cfg.rows_per_page or {}
        if not cfg:
            return
        val = str(cfg.get("value", 100))
        control_cfg = cfg.get("control")
        if not control_cfg:
            return
        try:
            control = resolver.locate(root, SelectorSet([SelectorCandidate(**c) for c in control_cfg["candidates"]]))
            tag = (control.evaluate("el => el.tagName && el.tagName.toLowerCase()") or "").lower()
            if tag == "select":
                control.select_option(val)
            else:
                control.click()
                control.fill(val)
                control.press("Enter")
        except Exception:
            pass

    def _make_paginator(self, resolver: SelectorResolver, root: Locator | Page) -> Paginator:
        pc = self.cfg.pagination
        if not pc:
            return NextButtonPaginator(root, resolver, {"button": {"candidates": []}})
        if pc.strategy == "next_button":
            return NextButtonPaginator(root, resolver, pc.next_button or {"button": {"candidates": []}})
        if pc.strategy == "load_more":
            return LoadMorePaginator(root, resolver, pc.load_more or {"button": {"candidates": []}})
        if pc.strategy == "numbered":
            return NumberedPaginator(root, resolver, pc.numbered or {})
        if pc.strategy == "infinite_scroll":
            return InfiniteScrollPaginator(root, pc.infinite_scroll or {})
        msg = f"Unknown pagination strategy: {pc.strategy}"
        raise ValueError(msg)

    def run(self) -> pd.DataFrame:
        p = self.page
        p.goto(self.cfg.base_url, wait_until="domcontentloaded")

        resolver = SelectorResolver(p)

        # Optional auth hook (prefer storage_state overall)
        if self.auth:
            self.auth.login(p, self.cfg, resolver)

        root = self._enter_frames(resolver)
        self._wait_ready(resolver, root)
        self._set_rows_per_page(resolver, root)

        extractor = GenericExtractor(resolver, self.cfg, root)
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

            if (max_pages and page_i >= max_pages) or (max_rows and len(all_rows) >= max_rows):
                break

            if not paginator.next_page():
                break

            # Small pause to allow DOM to update between pages
            p.wait_for_timeout(250)

        dframe = self._to_dataframe(all_rows, header)
        dframe.attrs["page_count"] = page_i
        return dframe

    @staticmethod
    def _to_dataframe(rows: list[list[str]], header: list[str] | None) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        max_len = max(len(r) for r in rows)
        norm = [r + [""] * (max_len - len(r)) if len(r) < max_len else r[:max_len] for r in rows]
        if header and len(header) == max_len:
            cols = [c if c else f"col_{i}" for i, c in enumerate(header)]
            return pd.DataFrame(norm, columns=cols)
        return pd.DataFrame(norm, columns=[f"col_{i}" for i in range(max_len)])

# ----------------------------
# Utilities: load config
# ----------------------------

def load_config(path: str | Path) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Coerce nested dicts into dataclasses where needed
    pag = raw.get("pagination")
    if pag:
        raw["pagination"] = PaginationConfig(**pag)
    return Config(**raw)

# ----------------------------
# CLI
# ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=str, required=True, help="Path to selectors JSON")
    ap.add_argument("--csv", type=str, default="", help="Optional path to export CSV")
    args = ap.parse_args()

    cfg = load_config(args.config)

    scraper = GenericScraper(cfg)
    try:
        dframe = scraper.run()
    finally:
        scraper.close()

    print(f"Rows: {len(dframe)} | Cols: {len(dframe.columns)} | Pages: {dframe.attrs.get('page_count')}")
    print(dframe.head(10).to_string(index=False))

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        dframe.to_csv(out, index=False, encoding="utf-8")
        print(f"Saved CSV to: {out}")

if __name__ == "__main__":
    main()
