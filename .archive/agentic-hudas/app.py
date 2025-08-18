# app.py (refactored with Copilot-style layout)

import os

import streamlit as st
import streamlit.components.v1 as components
from agent.llm_agent import run_agent
from state import session
from ui import left_menu, quick_actions
from ui.components import message


# -----------------------------
# Send message
# -----------------------------
def send_message(user_text: str):
    session.add_message("user", user_text)
    message.user(user_text)

    if not st.session_state["ollama_ready"] or not st.session_state["selected_model"]:
        message.assistant("⚠️ Model not ready — check the 🧠 panel.")
        return

    assistant_container = st.chat_message("assistant")
    live = assistant_container.empty()
    buf: list[str] = []

    def on_token(t: str):
        buf.append(t)
        live.markdown("".join(buf))

    try:
        result = run_agent(
            prompt=user_text,
            model_name=st.session_state["selected_model"],
            data=st.session_state.get("df"),
            scraper_config=st.session_state.get("scraper_config_json"),
            rows_per_page=int(st.session_state.get("rows_per_page", 100)),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            keep_alive=st.session_state.get(
                "model_lifetime",
                session.DEFAULTS["model_lifetime"],
            ),
            stream=True,
            on_token=on_token,
        )
        final_text = result.get("content", "")
        final_data = result.get("data")
        live.markdown(final_text)
        session.add_message("assistant", final_text, final_data)
        if final_data is not None:
            message.assistant("", final_data)
    except Exception as e:
        err = f"Error: {e}"
        live.markdown(err)
        session.add_message("assistant", err)


# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Agentic Hudas", layout="wide")
session.ensure()

# -----------------------------
# Styles
# -----------------------------
st.markdown(
    """
    <style>
      .block-container { padding-top: 0.75rem; padding-bottom: 1rem; }
      .chat-panel {
        height: calc(100vh - 180px); /* adjust offset */
        overflow-y: auto;
        padding: 8px 10px 12px 10px;
        border: 1px solid #dcdcdc;
        border-radius: 8px;
        background: #fafafa;
      }
      .chat-panel::-webkit-scrollbar { width: 8px; }
      .chat-panel::-webkit-scrollbar-thumb {
        background-color: rgba(0,0,0,0.15);
        border-radius: 8px;
      }
      .section-title {
        margin: 0 0 8px 0;
        font-weight: 600;
        font-size: 1.05rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Sidebar / model controls
# -----------------------------
with st.sidebar:
    left_menu.render(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        default_model="gpt-oss:20b",
        keep_alive_default=session.DEFAULTS["model_lifetime"],
    )


# -----------------------------
# Conversation rendering
# -----------------------------
def render_chat_history():
    st.markdown('<div class="section-title">Conversation</div>', unsafe_allow_html=True)
    chat_area = st.container()

    with chat_area:
        st.markdown(
            """
            <style>
              [data-testid="stVerticalBlock"] > div:has(> .chat-panel) {
                  height: calc(100vh - 180px);
                  overflow-y: auto;
              }
            </style>
            """,
            unsafe_allow_html=True,
        )
        for msg in st.session_state["messages"]:
            if msg["role"] == "user":
                message.user(msg["content"])
            else:
                message.assistant(msg["content"], msg.get("data"))


# -----------------------------
# Workspace / left rail
# -----------------------------
def render_left_rail():
    render_chat_history()


# -----------------------------
# Workspace / right rail
# -----------------------------
def render_right_rail():
    st.markdown('<div class="section-title">Workspace</div>', unsafe_allow_html=True)

    # Model status
    with st.expander("Model Status", expanded=True):
        st.markdown(
            f"- **Model:** {st.session_state['selected_model'] or '—'}\n"
            f"- **Server Ready:** {'✅' if st.session_state['ollama_ready'] else '❌'}\n"
            f"- **Model Ready:** {'✅' if st.session_state['model_ready'] else '❌'}\n"
            f"- **Lifetime:** {st.session_state.get('model_lifetime', session.DEFAULTS['model_lifetime'])}\n"
            f"- **Expiry:** {st.session_state['model_expiry']}",
        )

    # Quick actions
    with st.expander("Quick Actions", expanded=False):
        quick_actions.render(send_message)

    # Data preview
    if st.session_state.get("df") is not None:
        with st.expander("Data Preview", expanded=False):
            st.dataframe(st.session_state["df"], use_container_width=True)


# -----------------------------
# Layout
# -----------------------------
left_col, right_col = st.columns([7, 5], gap="large")

with left_col:
    render_left_rail()


with right_col:
    render_right_rail()


# -----------------------------
# Input (always at bottom)
# -----------------------------
if prompt := st.chat_input("Type your message"):
    send_message(prompt)
