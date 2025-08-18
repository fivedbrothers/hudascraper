import streamlit as st

DEFAULTS = {
    "route": "chat",
    "show_quick_panel": True,
    "messages": [],
    "df": None,
    "ollama_ready": False,
    "selected_model": "",
    "model_ready": False,
    "model_lifetime": "15m",
    "model_size": "",
    "model_expiry": "",
    "rows_per_page": 100,
    "scraper_config_json": {},
}


def ensure():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v


def toggle(key: str):
    st.session_state[key] = not st.session_state.get(key, False)


def add_message(role: str, content: str, data=None):
    st.session_state["messages"].append(
        {"role": role, "content": content, "data": data},
    )
