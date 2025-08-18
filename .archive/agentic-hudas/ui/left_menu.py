from pathlib import Path

import streamlit as st
from scraping.config import ScraperConfig
from state.session import toggle
from ui.ollama_panel import render_ollama_control


def render(base_url: str, default_model: str, keep_alive_default: str = "15m"):
    st.button(
        "⚡",
        help="Toggle Quick Actions",
        use_container_width=True,
        on_click=lambda: toggle("show_quick_panel"),
    )

    # LLM popover
    with st.popover("AI Model", use_container_width=True):
        st.subheader("LLM Configuration")
        o_ready, m_ready, m_expiry, model = render_ollama_control(
            base_url=base_url,
            default_model=default_model,
            keep_alive_default=keep_alive_default,
        )

    # Scraper Configuration popover
    with st.popover("Scraper", use_container_width=True):
        st.subheader("Scraper Configuration")
        base = st.text_input(
            "Base URL",
            value="https://practice.expandtesting.com/dynamic-pagination-table",
        )
        data_tab_selector = st.text_input(
            "Data Tab selector", value="#tab-data",
        )
        table_selector = st.text_input(
            "Data Table selector", value="#example",
        )
        rows_per_page_selector = st.text_input(
            "Rows-per-Page selector", value="#example_length",
        )
        next_button_selector = st.text_input(
            "Next Button selector", value="#example_next",
        )
        next_button_disabled_attr = st.text_input(
            "Next Disabled attribute (empty if none)", value="true",
        )
        row_selector = st.text_input("Row selector", value="tbody > tr")
        cell_selector = st.text_input("Cell selector", value="td")

        st.divider()

        user_data_dir = st.text_input(
            "Persistent profile directory",
            value=str(Path.home() / ".playwright-profile"),
        )
        headless = st.toggle("Headless mode", value=True)
        browser = st.selectbox("Browser engine", options=["chromium"], index=0)

        rows_per_page = st.number_input(
            "Rows per page", min_value=10, max_value=500, value=100, step=10,
        )

        st.divider()

        auto_login_enabled = st.toggle("Enable auto-login", value=True)
        ms_username = st.text_input(
            "Username (email)", value="", autocomplete="username",
        )
        ms_password = st.text_input(
            "Password", value="", type="password", autocomplete="current-password",
        )
        stay_signed_in = st.toggle("Stay signed in", value=True)
        login_timeout_seconds = st.number_input(
            "Login timeout (seconds)", min_value=10, max_value=180, value=60, step=5,
        )

        st.divider()

        ms_email_selector = st.text_input(
            "Email input selector", value="input[name='loginfmt']",
        )
        ms_next_selector = st.text_input(
            "Next button selector",
            value="input[type='submit'][value='Next'], input[type='submit'][data-report-event='Signin_Submit']",
        )
        ms_password_selector = st.text_input(
            "Password input selector", value="input[name='passwd']",
        )
        ms_signin_selector = st.text_input(
            "Sign in button selector",
            value="input[type='submit'][value='Sign in'], input[type='submit'][data-report-event='Signin_Submit']",
        )
        ms_stay_signed_in_yes_selector = st.text_input(
            "Stay signed in - Yes button selector", value="input[id='idBtn_Back']",
        )

        config = ScraperConfig(
            base_url=base,
            data_tab_selector=data_tab_selector,
            table_selector=table_selector,
            row_selector=row_selector,
            cell_selector=cell_selector,
            rows_per_page_selector=rows_per_page_selector,
            next_button_selector=next_button_selector,
            next_button_disabled_attr=next_button_disabled_attr or None,
            browser=browser,
            user_data_dir=user_data_dir,
            headless=headless,
            auto_login_enabled=auto_login_enabled,
            ms_username=ms_username or None,
            ms_password=ms_password or None,
            stay_signed_in=stay_signed_in,
            login_timeout_seconds=int(login_timeout_seconds),
            ms_email_selector=ms_email_selector,
            ms_next_selector=ms_next_selector,
            ms_password_selector=ms_password_selector,
            ms_signin_selector=ms_signin_selector,
            ms_stay_signed_in_yes_selector=ms_stay_signed_in_yes_selector,
        )
        st.session_state["scraper_config_json"] = config.to_json_dict()
        st.session_state["rows_per_page"] = int(rows_per_page)

    st.session_state["ollama_ready"] = o_ready
    st.session_state["model_ready"] = m_ready
    st.session_state["model_expiry"] = m_expiry
    st.session_state["selected_model"] = model
