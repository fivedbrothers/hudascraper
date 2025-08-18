import json

import pandas as pd
import streamlit as st


def assistant(content, data=None):
    with st.chat_message("assistant"):
        st.markdown(
            f"<div class='assistant-msg'>{content}</div>", unsafe_allow_html=True
        )
        if data is not None:
            tabs = st.tabs(["Table", "JSON"])
            with tabs[0]:
                try:
                    df = pd.DataFrame(data)
                    st.dataframe(df, use_container_width=True)
                except Exception:
                    st.caption("Data not tabular.")
            with tabs[1]:
                st.code(json.dumps(data, indent=2), language="json")


def user(content):
    with st.chat_message("user"):
        st.markdown(f"<div class='user-msg'>{content}</div>", unsafe_allow_html=True)
