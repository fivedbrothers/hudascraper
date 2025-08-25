import contextlib
import json
import logging
import subprocess
import time
from typing import Any

import pandas as pd
import requests
import streamlit as st

from hudascraper.web import ServerManager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ----------------------------
# Page setup
# ----------------------------
st.set_page_config(page_title="HudaScraper", layout="wide")
st.title("HudaScraper")

st.markdown(
    """
    <style>
    .stTextInput > div > div > input, .stTextArea textarea, .stNumberInput input {
        border-radius: 6px;
    }
    .stButton>button {
        border-radius: 6px;
        height: 2.4rem;
    }
    .small-muted { color: #6b7280; font-size: 0.9rem; }
    .metric-box { padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------
# Server manager (session-scoped)
# ----------------------------
def get_manager() -> ServerManager:
    if "server" not in st.session_state:
        st.session_state.server = ServerManager(
            app_path="hudascraper.web:server",
            host="127.0.0.1",
            port=8000,
            reload=False,
        )
    return st.session_state.server


sm = get_manager()

# Ensure the managed server is stopped when this process exits
import atexit

with contextlib.suppress(Exception):
    atexit.register(lambda: sm.stop())

# Persist last run across tabs
if "last_run_id" not in st.session_state:
    st.session_state.last_run_id = ""

# ----------------------------
# Sidebar: server controls
# ----------------------------
st.sidebar.header("Server")
app_path = st.sidebar.text_input("Application Path", sm.app_path)
host = st.sidebar.text_input("Host", sm.host)
port = st.sidebar.number_input(
    "Port",
    min_value=1,
    max_value=65535,
    value=sm.port,
    step=1,
)
reload = st.sidebar.checkbox(
    "Enable reload (dev)",
    value=sm.reload,
    help="May disrupt log capture",
)

apply = st.sidebar.button("Apply settings", use_container_width=True)
start = st.sidebar.button("Start server", use_container_width=True)
stop = st.sidebar.button("Stop server", use_container_width=True)

if apply:
    if sm.is_managed_running():
        st.sidebar.warning("Stop the server before changing settings.")
    else:
        st.session_state.server = ServerManager(
            app_path=app_path, host=host, port=int(port), reload=reload,
        )
        sm = st.session_state.server
        st.sidebar.success("Settings applied.")

if start:
    try:
        sm.start()
        st.sidebar.success("Start requested.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        logger.exception("Server start failed")
        st.sidebar.error(f"Failed to start: {e}")

if stop:
    try:
        sm.stop()
        st.sidebar.info("Stop requested.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        logger.exception("Server stop failed")
        st.sidebar.error(f"Failed to stop: {e}")

# ----------------------------
# Status row
# ----------------------------
status_cols = st.columns(3)
with status_cols[0]:
    st.markdown(
        '<div class="metric-box">HTTP reachable<br><b>{}</b></div>'.format(
            "Yes" if sm.is_http_up() else "No",
        ),
        unsafe_allow_html=True,
    )
with status_cols[1]:
    st.markdown(
        '<div class="metric-box">Managed process<br><b>{}</b></div>'.format(
            "Running" if sm.is_managed_running() else "Stopped",
        ),
        unsafe_allow_html=True,
    )
with status_cols[2]:
    st.markdown(
        f'<div class="metric-box">Base URL<br><b>{sm.base_url()}</b></div>',
        unsafe_allow_html=True,
    )

st.markdown(
    '<div class="small-muted">Tip: Keep reload off for stable logs. The UI can also auto-start the server on scrape.</div>',
    unsafe_allow_html=True,
)

st.divider()


# ----------------------------
# Helpers
# ----------------------------
def _safe_json_loads(s: str) -> str:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError) as e:
        msg = f"Invalid JSON: {e}"
        raise ValueError(msg)


def _post_scrape(
    base_url: str,
    config_obj: dict[str, Any],
    wrapped: bool,
    username: str,
    password: str,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/scrape"
    params = {}
    if username:
        params["username"] = username
    if password:
        params["password"] = password

    body = {"config": config_obj} if wrapped else config_obj
    resp = requests.post(url, params=params, json=body, timeout=600)
    resp.raise_for_status()
    return resp.json()


def _get_results(base_url: str, run_id: str) -> pd.DataFrame:
    # FastAPI route: GET /results/{run_id}
    url = f"{base_url.rstrip('/')}/results/{run_id}"
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    items: list[dict[str, Any]] = (
        data.get("items", []) if isinstance(data, dict) else data
    )
    return pd.DataFrame(items)


# ----------------------------
# Layout: tabs
# ----------------------------
tab_scrape, tab_results, tab_logs = st.tabs(["Scrape", "Results", "Server logs"])

# ----------------------------
# Scrape tab
# ----------------------------
with tab_scrape:
    st.subheader("Scrape")

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.markdown("**Config JSON**")
        cfg_source = st.radio(
            "Source",
            options=["Upload file", "Paste JSON"],
            horizontal=True,
            label_visibility="collapsed",
        )

        config_obj: dict[str, Any] | None = None
        if cfg_source == "Upload file":
            uploaded = st.file_uploader(
                "Upload your config.json",
                type=["json"],
                accept_multiple_files=False,
            )
            if uploaded is not None:
                try:
                    content = uploaded.read().decode("utf-8")
                    config_obj = _safe_json_loads(content)
                    st.success("Config loaded.")
                except (ValueError, UnicodeDecodeError) as e:
                    st.error(str(e))
                    logger.debug("Config upload failed: %s", e)
        else:
            cfg_text = st.text_area(
                "Paste JSON",
                height=240,
                placeholder="{\n  \n}",
            )
            if cfg_text.strip():
                try:
                    config_obj = _safe_json_loads(cfg_text)
                except ValueError as e:
                    st.error(str(e))
                    logger.debug("Pasted config failed to parse: %s", e)

    with col_right:
        st.markdown("**Credentials**")
        username = st.text_input("Username", value="")
        password = st.text_input("Password", type="password", value="")

        st.markdown("**Request options**")
        wrapped = st.checkbox(
            "Wrap body as {'config': {...}}",
            value=False,
            help="Enable if your API expects the config wrapped in a 'config' key.",
        )
        auto_fetch = st.checkbox("Auto-fetch results after scrape", value=True)
        auto_start = st.checkbox("Auto-start server if not running", value=True)

        st.markdown(
            f'<div class="small-muted">Server URL is fixed to the managed process: {sm.base_url()}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    submit_col, info_col = st.columns([1, 3])
    with submit_col:
        run = st.button(
            "Start scrape",
            type="primary",
            use_container_width=True,
            disabled=not bool(config_obj),
        )
    with info_col:
        st.markdown(
            '<div class="small-muted">Provide a valid config and click Start.</div>',
            unsafe_allow_html=True,
        )

    if run:
        if not config_obj:
            st.error("Please provide a valid config JSON.")
        else:
            try:
                if auto_start:
                    with st.spinner("Ensuring server is running..."):
                        sm.ensure_running()
                        # brief wait if just started
                        for _ in range(12):
                            if sm.is_http_up():
                                break
                            time.sleep(0.25)

                if not sm.is_http_up():
                    st.error("Server is not reachable. Check the Server logs tab.")
                else:
                    with st.spinner("Submitting scrape job..."):
                        res = _post_scrape(
                            sm.base_url(),
                            config_obj,
                            wrapped,
                            username.strip(),
                            password,
                        )
                        run_id = str(res.get("run_id", ""))
                        if not run_id:
                            st.warning(
                                f"Scrape submitted, but no run_id returned. Response: {res}",
                            )
                        else:
                            st.session_state.last_run_id = run_id
                            st.success(f"Scrape started. run_id: {run_id}")

                        if auto_fetch and run_id:
                            st.divider()
                            st.markdown("#### Extracted data")
                            try:
                                # Light polling in case results write is async
                                dframe: pd.DataFrame | None = None
                                for _ in range(10):
                                    try:
                                        dframe = _get_results(sm.base_url(), run_id)
                                        break
                                    except requests.RequestException:
                                        time.sleep(0.8)
                                if dframe is None:
                                    dframe = _get_results(sm.base_url(), run_id)

                                if dframe.empty:
                                    st.info("No rows returned.")
                                else:
                                    st.dataframe(
                                        dframe,
                                        use_container_width=True,
                                        height=420,
                                    )
                                    csv = dframe.to_csv(index=False).encode("utf-8")
                                    st.download_button(
                                        "Download CSV",
                                        data=csv,
                                        file_name=f"hudascraper_{run_id}.csv",
                                        mime="text/csv",
                                        use_container_width=True,
                                    )
                            except (requests.RequestException, ValueError) as e:
                                st.warning(f"Unable to fetch results yet: {e}")
                                logger.debug("Fetching results failed: %s", e)
                            except Exception:
                                logger.exception("Unexpected error fetching results")
                                st.warning(
                                    "Unable to fetch results yet: an unexpected error occurred",
                                )
            except requests.HTTPError as http_err:
                try:
                    err_json = http_err.response.json()
                except ValueError:
                    err_json = http_err.response.text
                st.error(f"HTTP {http_err.response.status_code}: {err_json}")
                logger.debug("Scrape submission HTTP error: %s", http_err)
            except (requests.RequestException, ValueError) as e:
                st.error(f"Failed to submit scrape: {e}")
                logger.debug("Scrape submission failed: %s", e)
            except Exception:
                logger.exception("Unexpected error during scrape submission")
                st.error("Failed to submit scrape: an unexpected error occurred")

# ----------------------------
# Results tab
# ----------------------------
with tab_results:
    st.subheader("Results")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        run_id_in = st.text_input(
            "run_id",
            value=st.session_state.last_run_id,
            placeholder="e.g., 1692149123",
            help="Enter the run_id returned by the /scrape endpoint.",
        )
    with col_b:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        fetch_btn = st.button(
            "Fetch results",
            use_container_width=True,
            disabled=not run_id_in,
        )

    if fetch_btn:
        if auto_start:
            with st.spinner("Ensuring server is running..."):
                sm.ensure_running()
        if not sm.is_http_up():
            st.error("Server is not reachable. Check the Server logs tab.")
        else:
            with st.spinner("Fetching results..."):
                try:
                    dframe = _get_results(sm.base_url(), run_id_in.strip())
                    if dframe.empty:
                        st.info("No rows returned for this run_id.")
                    else:
                        st.markdown("#### Extracted data")
                        st.dataframe(dframe, use_container_width=True, height=500)
                        csv = dframe.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "Download CSV",
                            data=csv,
                            file_name=f"hudascraper_{run_id_in}.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )
                except requests.HTTPError as http_err:
                    try:
                        err_json = http_err.response.json()
                    except ValueError:
                        err_json = http_err.response.text
                    st.error(f"HTTP {http_err.response.status_code}: {err_json}")
                    logger.debug("Results fetch HTTP error: %s", http_err)
                except (requests.RequestException, ValueError) as e:
                    st.error(f"Failed to fetch results: {e}")
                    logger.debug("Results fetch failed: %s", e)
                except Exception:
                    logger.exception("Unexpected error fetching results")
                    st.error("Failed to fetch results: an unexpected error occurred")

# ----------------------------
# Server logs tab
# ----------------------------
with tab_logs:
    st.subheader("Server Logs")

    lc1, lc2, lc3 = st.columns([1, 1, 2])
    with lc1:
        if st.button("Clear Logs"):
            sm.clear_logs()
    with lc2:
        manual_refresh = st.button("Refresh now")

    auto_refresh = st.checkbox("Auto-refresh logs", value=False)
    interval = st.slider("Refresh interval (s)", 1, 10, 2)

    st.text_area(
        "Live log tail",
        value=sm.tail_logs(800),
        height=420,
        label_visibility="collapsed",
    )

    if manual_refresh or (
        auto_refresh and st.session_state.get("autorefresh_tick", 0) >= 0
    ):
        time.sleep(interval)
        st.session_state["autorefresh_tick"] = (
            st.session_state.get("autorefresh_tick", 0) + 1
        )
        st.rerun()
