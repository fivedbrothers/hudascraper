import json
from pathlib import Path

import streamlit as st


def render(send_message):
    if not st.session_state.get("show_quick_panel", True):
        return
    with st.container(border=False):
        # st.markdown("#### Quick actions")
        qa_col1, qa_col2 = st.columns(2)
        with qa_col1:
            if st.button("Extract all pages", use_container_width=True):
                send_message(
                    "Extract all pages with the provided scraper_config and rows_per_page. Summarize rows and columns.",
                )
            if st.button("Profile data", use_container_width=True):
                send_message(
                    "Profile the current dataset (use data_profile) and present schema, null counts, and key stats.",
                )
            if st.button("Preview 30 rows", use_container_width=True):
                send_message(
                    "Preview the first 30 rows of the current dataset (use preview_rows with n=30).",
                )
        with qa_col2:
            filter_query = st.text_input(
                "Filter (pandas query)", key="qa_filter_query", value="",
            )
            if st.button("Apply filter", use_container_width=True):
                send_message(
                    f"Filter rows using: {json.dumps({'query': filter_query, 'n': 20})}. Use filter_rows tool with these args.",
                )
            save_path = st.text_input(
                "Save CSV path",
                key="qa_save_path",
                value=str(Path.cwd() / "extracted_data.csv"),
            )
            if st.button("Save CSV", use_container_width=True):
                send_message(
                    f"Save the current dataset to CSV at path: {save_path}. Use save_csv tool with this path.",
                )
