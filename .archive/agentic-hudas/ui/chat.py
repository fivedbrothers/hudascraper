import pandas as pd
import streamlit as st
from ui.components import message


def render(send_message):
    st.markdown("## Agent Chat")
    st.caption(
        "Use the chat or Quick actions. The agent executes tools for all operations."
    )

    # History
    for m in st.session_state["messages"]:
        if m["role"] == "user":
            message.user(m["content"])
        else:
            message.assistant(m["content"], m.get("data"))

    # Input
    if prompt := st.chat_input("Ask the agent to extract, analyze, filter, or save."):
        # Append and invoke
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            out = send_message(prompt)
            st.markdown(out)

    # Inline Data panel
    st.markdown("## Data")
    df = st.session_state.get("df")
    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
        st.caption("Latest extracted dataset")
        st.dataframe(df.head(200), use_container_width=True)

        st.markdown("#### Download")
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name="extracted_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.info("No data in memory. Use Quick actions or chat to extract the table.")
