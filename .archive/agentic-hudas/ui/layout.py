from pathlib import Path

import streamlit as st


def apply_page():
    st.set_page_config(page_title="Agentic Hudas", layout="wide")
    css_path = Path("styles/theme.css")
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)
