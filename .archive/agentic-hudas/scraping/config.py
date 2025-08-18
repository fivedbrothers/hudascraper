# Scraper configuration extended to include Microsoft login behavior and selectors.

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ScraperConfig:
    # Page & structure
    base_url: str
    data_tab_selector: str
    table_selector: str
    row_selector: str
    cell_selector: str
    rows_per_page_selector: str
    next_button_selector: str
    next_button_disabled_attr: str | None = None

    # Browser/session
    browser: str = "chromium"
    user_data_dir: str | None = None
    headless: bool = True

    # Microsoft login behavior
    auto_login_enabled: bool = True
    ms_username: str | None = None
    ms_password: str | None = None
    stay_signed_in: bool = True
    login_timeout_seconds: int = 60

    # Microsoft login selectors
    ms_email_selector: str = "input[name='loginfmt']"
    ms_next_selector: str = "input[type='submit'][value='Next'], input[type='submit'][data-report-event='Signin_Submit']"
    ms_password_selector: str = "input[name='passwd']"
    ms_signin_selector: str = "input[type='submit'][value='Sign in'], input[type='submit'][data-report-event='Signin_Submit']"
    ms_stay_signed_in_yes_selector: str = "input[id='idBtn_Back']"  # "Yes" button

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Avoid exposing password when echoing config to UI/chat contexts
        if "ms_password" in d and d["ms_password"] is not None:
            d["ms_password"] = "***"
        return d

    @staticmethod
    def from_json_dict(d: dict[str, Any]) -> "ScraperConfig":
        return ScraperConfig(
            base_url=d.get("base_url", ""),
            data_tab_selector=d.get("data_tab_selector", ""),
            table_selector=d.get("table_selector", ""),
            row_selector=d.get("row_selector", ""),
            cell_selector=d.get("cell_selector", ""),
            rows_per_page_selector=d.get("rows_per_page_selector", ""),
            next_button_selector=d.get("next_button_selector", ""),
            next_button_disabled_attr=d.get("next_button_disabled_attr"),
            browser=d.get("browser", "chromium"),
            user_data_dir=d.get("user_data_dir"),
            headless=bool(d.get("headless", True)),
            auto_login_enabled=bool(d.get("auto_login_enabled", True)),
            ms_username=d.get("ms_username"),
            # Accept raw password in tool-side config (not echoed back to chat)
            ms_password=d.get("ms_password")
            if d.get("ms_password") not in ("***", None)
            else None,
            stay_signed_in=bool(d.get("stay_signed_in", True)),
            login_timeout_seconds=int(d.get("login_timeout_seconds", 60)),
            ms_email_selector=d.get("ms_email_selector", "input[name='loginfmt']"),
            ms_next_selector=d.get(
                "ms_next_selector",
                "input[type='submit'][value='Next'], input[type='submit'][data-report-event='Signin_Submit']",
            ),
            ms_password_selector=d.get("ms_password_selector", "input[name='passwd']"),
            ms_signin_selector=d.get(
                "ms_signin_selector",
                "input[type='submit'][value='Sign in'], input[type='submit'][data-report-event='Signin_Submit']",
            ),
            ms_stay_signed_in_yes_selector=d.get(
                "ms_stay_signed_in_yes_selector", "input[id='idBtn_Back']",
            ),
        )
