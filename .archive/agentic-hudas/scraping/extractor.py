# Playwright-based extractor with conditional Microsoft SSO auto-login.
# - Uses a persistent profile to keep cookies between runs.
# - If redirected to Microsoft login, performs email/password flow (and "Stay signed in" if enabled).
# - Navigates to the data tab, sets rows-per-page, and paginates across all pages to collect rows.

from time import monotonic

import pandas as pd
from playwright.sync_api import BrowserContext, Page, sync_playwright
from scraping.config import ScraperConfig


class PlaywrightScraper:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self._play = sync_playwright().start()
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._launch()

    def _launch(self):
        """
        Launch SSO context.

        Launch a persistent context if user_data_dir is provided, preserving SSO cookies.
        """
        browser_type = getattr(self._play, self.config.browser)
        if self.config.user_data_dir:
            self._context = browser_type.launch_persistent_context(
                user_data_dir=self.config.user_data_dir,
                headless=self.config.headless,
                args=["--disable-dev-shm-usage"],
            )
        else:
            browser = browser_type.launch(headless=self.config.headless)
            self._context = browser.new_context()
        self._page = self._context.new_page()

    def _on_ms_login_page(self) -> bool:
        """
        Microsoft login page check.

        Detect whether we are on a Microsoft login page (heuristic).
        """
        assert self._page is not None
        url = self._page.url or ""
        if "login.microsoftonline.com" in url or "login.live.com" in url:
            return True
        try:
            if self._page.locator(self.config.ms_email_selector).first.count() > 0:
                return True
        except Exception:
            pass
        return False

    def _perform_ms_login(self):
        """
        Microsoft Login.

        Automate Microsoft login:
        - Fill email -> Next
        - Fill password -> Sign in
        - Optionally confirm 'Stay signed in' prompt
        Waits until redirected away from login to the app or until timeout.
        """
        assert self._page is not None
        p = self._page
        if not (self.config.ms_username and self.config.ms_password):
            # Credentials not provided; skip attempting login.
            return

        deadline = monotonic() + max(10, int(self.config.login_timeout_seconds))

        def time_left() -> float:
            return max(0.0, deadline - monotonic())

        try:
            # Email
            p.locator(self.config.ms_email_selector).first.wait_for(
                state="visible", timeout=min(10_000, int(time_left() * 1000)),
            )
            p.fill(self.config.ms_email_selector, self.config.ms_username)
            p.locator(self.config.ms_next_selector).first.click(
                timeout=min(10_000, int(time_left() * 1000)),
            )

            # Password
            p.locator(self.config.ms_password_selector).first.wait_for(
                state="visible", timeout=min(20_000, int(time_left() * 1000)),
            )
            p.fill(self.config.ms_password_selector, self.config.ms_password)
            p.locator(self.config.ms_signin_selector).first.click(
                timeout=min(10_000, int(time_left() * 1000)),
            )

            # Optional: Stay signed in prompt
            if self.config.stay_signed_in:
                try:
                    p.locator(
                        self.config.ms_stay_signed_in_yes_selector
                    ).first.wait_for(state="visible", timeout=5_000)
                    p.locator(self.config.ms_stay_signed_in_yes_selector).first.click()
                except Exception:
                    pass  # Prompt may not appear
        except Exception:
            # Let subsequent waits decide outcome
            pass

        # Wait for redirect back to the app or completion of login
        # We either see the base_url domain, or we leave the login domain, or table appears.
        while time_left() > 0:
            url = p.url or ""
            if ("login.microsoftonline.com" not in url) and (
                "login.live.com" not in url
            ):
                break
            p.wait_for_timeout(300)

    def _goto_and_prepare(self):
        assert self._page is not None
        p = self._page
        p.goto(self.config.base_url, wait_until="domcontentloaded")

        if self.config.auto_login_enabled and self._on_ms_login_page():
            self._perform_ms_login()
            p.goto(self.config.base_url, wait_until="domcontentloaded")

        try:
            p.get_by_role("tab", name="Data").click(timeout=5_000)
        except Exception:
            try:
                p.locator(self.config.data_tab_selector).first.click(timeout=5_000)
            except Exception:
                pass

        # Fallback sequence for waiting on table
        locators_to_try = [
            lambda: p.get_by_role("table", name="Main table").first,
            lambda: p.locator(self.config.table_selector).first,
            lambda: p.locator("table").first,  # generic table
        ]
        found = False
        for get_loc in locators_to_try:
            try:
                get_loc().wait_for(state="visible", timeout=10_000)
                found = True
                self._table_locator = get_loc()
                break
            except Exception:
                continue
        if not found:
            raise RuntimeError("Table element not found after trying fallback locators")


    def _set_rows_per_page(self, rows: int):
        """
        Set the total rows-per-page value.

        Attempt to set the rows-per-page control if present.
        """
        p = self._page
        if not p or not self.config.rows_per_page_selector:
            return
        sel = p.locator(self.config.rows_per_page_selector).first
        try:
            sel.wait_for(state="visible", timeout=5_000)
            tag = sel.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                sel.select_option(str(rows))
            else:
                sel.click()
                sel.fill(str(rows))
                sel.press("Enter")
        except Exception:
            pass  # Continue with current rows-per-page

    def _extract_current_page(self) -> list[list[str]]:
        """
        Read visible table rows and cells.

        Returns a list of row arrays. If a THEAD is present, header is captured separately.

        """
        p = self._page
        assert p is not None
        # Try to read header
        headers: list[str] = []
        try:
            headers = p.locator(
                f"{self.config.table_selector} thead tr th",
            ).all_inner_texts()
            headers = [h.strip() for h in headers]
        except Exception:
            headers = []

        # Body rows
        rows: list[list[str]] = []
        table_loc = getattr(self, "_table_locator", None) or p.locator(self.config.table_selector).first
        headers = table_loc.locator("thead tr th").all_inner_texts()
        row_loc = table_loc.locator("tbody tr")

        count = row_loc.count()
        for i in range(count):
            cell_texts = (
                row_loc.nth(i).locator(self.config.cell_selector).all_inner_texts()
            )
            rows.append([c.strip() for c in cell_texts])

        return [headers] + rows if headers else rows

    def _click_next(self) -> bool:
        """
        Click the Next button if enabled. Return False if this is the last page.

        Returns bool

        """
        p = self._page
        assert p is not None
        btn = p.locator(self.config.next_button_selector).first
        try:
            btn.wait_for(state="attached", timeout=5_000)
        except Exception:
            return False
        try:
            if self.config.next_button_disabled_attr:
                disabled = btn.get_attribute(self.config.next_button_disabled_attr)
                if disabled is not None:
                    return False
            aria_disabled = btn.get_attribute("aria-disabled")
            if aria_disabled in ("true", "True"):
                return False
            btn.click()
            p.wait_for_timeout(300)
        except Exception:
            return False
        else:
            return True

    def extract_all_pages(self, rows_per_page: int = 100) -> pd.DataFrame:
        """
        High-level extraction.

        Ensure we are logged in, navigate to table, set rows-per-page,
        paginate to collect all rows, and build a DataFrame. Page count stored in df.attrs.

        Returns extracted data

        """
        self._goto_and_prepare()
        self._set_rows_per_page(rows_per_page)

        all_rows: list[list[str]] = []
        header: list[str] | None = None
        page_count = 0

        while True:
            page_count += 1
            rows = self._extract_current_page()
            if (
                rows
                and isinstance(rows[0], list)
                and header is None
                and self._looks_like_header(rows[0])
            ):
                header = rows[0]
                data_rows = rows[1:]
            else:
                data_rows = rows
            all_rows.extend(data_rows)

            if not self._click_next():
                break

        df = self._to_dataframe(all_rows, header)
        df.attrs["page_count"] = page_count
        return df

    @staticmethod
    def _looks_like_header(row: list[str]) -> bool:
        if not row:
            return False
        alpha = sum(ch.isalpha() for cell in row for ch in cell)
        total = max(1, sum(len(cell) for cell in row))
        return (alpha / total) > 0.4

    @staticmethod
    def _to_dataframe(
        rows: list[list[str]], header: list[str] | None,
    ) -> pd.DataFrame:
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
        else:
            cols = [f"col_{i}" for i in range(max_len)]
            return pd.DataFrame(norm, columns=cols)

    def close(self):
        """
        Close resources.

        Close resources cleanly.

        """
        try:
            if self._context:
                self._context.close()
        finally:
            if self._play:
                self._play.stop()
