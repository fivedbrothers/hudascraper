# Streamlit UI controls for Ollama server: model selection, start/stop, pull, and status.

from __future__ import annotations

import os

import streamlit as st
from infra.ollama_health import DEFAULT_OLLAMA_BASE_URL, OllamaHealth


def render_ollama_control(
    base_url: str | None = None,
    default_model: str = "gpt-oss:20b",
    keep_alive_default: str = "15m",
) -> tuple[bool, str]:
    base_url = (
        base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
    ).rstrip("/")
    health = OllamaHealth(base_url)

    st.caption(f"Base URL: {base_url}")
    ok, detail = health.ping(timeout=1.2)
    if not ok:
        st.error(f"Ollama not reachable. {detail}")
        st.markdown(
            "- Start server: `ollama serve`\n"
            "- Default URL: http://localhost:11434\n"
            "- Configure via OLLAMA_BASE_URL if different.",
        )
        if st.button("Retry connection", type="primary"):
            st.rerun()
        return False, ""

    st.success("Connected")

    # Inventory
    try:
        models = health.list_models()
    except Exception as e:
        models = []
        st.warning(f"Could not list models: {e}")

    # Model selection
    model = st.selectbox(
        "Model",
        options=models if models else [default_model],
        index=(models.index(default_model) if default_model in models else 0),
        help="Pick the model tag (e.g., gpt-oss:20b, llama3).",
    )

    cols = st.columns(2)

    with cols[0]:
        keep_alive = st.text_input(
            "Keep-alive",
            value=keep_alive_default,
            help="e.g., 10m, 1h, or -1 to pin",
        )
        st.session_state["model_lifetime"] = keep_alive or keep_alive_default
    with cols[1]:
        if st.button("Refresh", use_container_width=True):
            st.rerun()
    # with cols[1]:
    #     st.caption("")

    # Running models snapshot
    with st.expander("Running models", expanded=False):
        try:
            running = health.list_running()
            if running:
                for m in running:
                    st.write(
                        f"- {m.get('model')}  •  size={m.get('size')}  •  expires_at={m.get('expires_at')}",
                    )
            else:
                st.caption("No models currently loaded.")
        except Exception as e:
            st.caption(f"Could not query running models: {e}")

    # Actions
    act_cols = st.columns(3)
    with act_cols[0]:
        if st.button("Start", type="primary", use_container_width=True):
            ok_s, msg = health.start_model(
                model,
                keep_alive=st.session_state.get(
                    "model_lifetime",
                    keep_alive_default,
                ),
            )
            (st.success if ok_s else st.error)(msg)
    with act_cols[1]:
        if st.button("Stop", use_container_width=True):
            ok_t, msg = health.stop_model(model)
            (st.success if ok_t else st.error)(msg)
    with act_cols[2]:
        if model and model not in models:
            if st.button(f"Pull '{model}'", use_container_width=True):
                with st.status(f"Pulling {model} …", expanded=True) as status:
                    ok_p, msg = health.pull_model(model)
                    if ok_p:
                        status.update(label=f"Pulled {model}", state="complete")
                        st.success(msg)
                        st.rerun()
                    else:
                        status.update(label="Pull failed", state="error")
                        st.error(msg)
        else:
            st.caption("")

    # Ready if model exists locally and running
    server_ready = model in models
    model_ready = False
    model_expiry = ""
    if not server_ready:
        st.warning(f"Model not installed: {model}. Pull it to proceed.")
    else:
        model_ready, msg = health.is_model_running(name=model)
        if model_ready:
            model_expiry = health.get_model_expiry(name=model)
            st.success(msg)
        else:
            st.warning(msg)
    return server_ready, model_ready, model_expiry, model
