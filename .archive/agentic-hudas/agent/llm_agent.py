# LangChain ReAct agent over local Ollama with a ReAct-compatible prompt.
# - Tools are the only way the agent can act (extraction, profiling, filtering, saving).
# - Prompt includes required placeholders: {tools}, {tool_names}, {agent_scratchpad}, {input}

import contextlib
import json
import os
from collections.abc import Callable
from typing import Any

from agent.tools import (
    tool_data_profile,
    tool_extract_all_pages,
    tool_filter_rows,
    tool_preview_rows,
    tool_save_csv,
)
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import StructuredTool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

SYSTEM_RULES = """You are an operations agent for a data extraction app.
- You must use tools to perform any extraction, inspection, filtering, or saving.
- Never fabricate data; if no data exists in memory, extract it first.
- When the user provides a scraper configuration in the message context, use it.
- For analysis, first profile the data, then answer succinctly with concrete facts.
- Save to CSV only if the user explicitly asks to save or download.
Return clear, direct answers; include brief counts or column names when helpful."""

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """{system_rules}

You have access to the following tools:
{tools}

Tool names: {tool_names}

Follow the ReAct pattern:
1. Think about whether a tool is needed.
2. If needed, pick the correct tool with appropriate arguments.
3. After using tools as necessary, provide a clear final answer to the user.""",
        ),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ],
)


def _select_data_payload(state: dict[str, Any]) -> Any:
    """Prefer preview/filtered/profile; fall back to df."""
    for k in ["preview", "filtered", "profile", "last_result", "last_data", "df"]:
        if k in state and state[k] is not None:
            return state[k]
    return None


# ---------- Arg schemas ----------
class ExtractAllPagesArgs(BaseModel):
    rows_per_page: int = Field(
        100, description="Rows per page to select in the UI before scraping"
    )
    scraper_config: dict[str, Any] = Field(
        ..., description="Scraper configuration for pagination/table selectors"
    )


class DataProfileArgs(BaseModel):
    # Optional payload if you want to scope or include columns; can remain empty
    include: list[str] | None = Field(
        default=None, description="Optional subset of columns to profile"
    )


class PreviewRowsArgs(BaseModel):
    n: int = Field(
        20, ge=1, le=200, description="Number of rows to preview (capped for UI)"
    )


class FilterRowsArgs(BaseModel):
    query: str = Field(
        ...,
        description="pandas.DataFrame.query expression, e.g., \"status == 'Open' and amount > 1000\"",
    )
    n: int | None = Field(
        20, ge=1, le=200, description="Optional preview row count after filtering"
    )


class SaveCsvArgs(BaseModel):
    path: str = Field(..., description="Filesystem path to write the CSV to")


def build_agent(state: dict[str, Any]) -> AgentExecutor:
    # Structured tool wrappers adapt typed args -> your existing tool functions
    def _extract_all_pages(**kwargs):
        args = ExtractAllPagesArgs(**kwargs)
        return tool_extract_all_pages(state, args.model_dump(exclude_none=True))

    def _data_profile(**kwargs):
        args = DataProfileArgs(**kwargs)
        return tool_data_profile(state, args.model_dump(exclude_none=True))

    def _preview_rows(**kwargs):
        args = PreviewRowsArgs(**kwargs)
        return tool_preview_rows(state, args.model_dump(exclude_none=True))

    def _filter_rows(**kwargs):
        args = FilterRowsArgs(**kwargs)
        return tool_filter_rows(state, args.model_dump(exclude_none=True))

    def _save_csv(**kwargs):
        args = SaveCsvArgs(**kwargs)
        return tool_save_csv(state, args.model_dump(exclude_none=True))

    tools = [
        StructuredTool.from_function(
            name="extract_all_pages",
            description="Extract all rows from the paginated table using the given scraper_config.",
            func=_extract_all_pages,
            args_schema=ExtractAllPagesArgs,
        ),
        StructuredTool.from_function(
            name="data_profile",
            description="Profile the in-memory dataset for quick factual analysis.",
            func=_data_profile,
            args_schema=DataProfileArgs,
        ),
        StructuredTool.from_function(
            name="preview_rows",
            description="Preview the first N rows from the current in-memory dataset.",
            func=_preview_rows,
            args_schema=PreviewRowsArgs,
        ),
        StructuredTool.from_function(
            name="filter_rows",
            description="Filter rows via pandas query and optionally preview N rows of the result.",
            func=_filter_rows,
            args_schema=FilterRowsArgs,
        ),
        StructuredTool.from_function(
            name="save_csv",
            description="Save the current dataset to a CSV file at the specified path.",
            func=_save_csv,
            args_schema=SaveCsvArgs,
        ),
    ]

    tool_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    tool_names = ", ".join(t.name for t in tools)

    prompt = PROMPT.partial(
        system_rules=SYSTEM_RULES, tools=tool_desc, tool_names=tool_names
    )

    # Respect state overrides for Ollama connection and behavior
    model = state.get("agent_model") or "gpt-oss:20b"
    lifetime = state.get("ollama_keep_alive") or os.getenv("OLLAMA_KEEP_ALIVE", "15m")
    url = state.get("ollama_base_url") or os.getenv(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    )
    temperature = state.get("temperature", 0.1)

    llm = ChatOllama(
        model=model, temperature=temperature, base_url=url, keep_alive=lifetime
    )

    agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        return_intermediate_steps=False,
    )
    return executor


def run_agent(
    prompt: str,
    model_name: str,
    data: Any | None = None,
    scraper_config: dict | None = None,
    rows_per_page: int = 100,
    *,
    base_url: str | None = None,
    keep_alive: str | None = None,
    stream: bool = True,
    on_token: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Executes the ReAct agent.

    If `stream=True` and the AgentExecutor supports streaming via `.stream`,
    this function emits token chunks through the `on_token` callback while
    accumulating the final response.

    Returns
    -------
        dict: {
            "content": <final generated text>,
            "data": <optional payload, if any>
        }

    """
    # Ensure build_agent picks up the right transport
    if base_url:
        os.environ["OLLAMA_BASE_URL"] = base_url

    # Shared, mutable state for tools
    state: dict[str, Any] = {
        "df": data,
        "scraper_config": scraper_config or {},
        "rows_per_page": rows_per_page,
        "agent_model": model_name,
        "ollama_keep_alive": keep_alive or os.getenv("OLLAMA_KEEP_ALIVE", "15m"),
    }

    executor = build_agent(state)

    # augment message so the agent "sees" config every run
    context = {
        "scraper_config": state["scraper_config"],
        "rows_per_page": rows_per_page,
    }
    augmented = (
        "Context:\n" + json.dumps(context, indent=2) + "\n\nUser request:\n" + prompt
    )

    content = ""
    try:
        if stream and hasattr(executor, "stream"):
            buf: list[str] = []
            for chunk in executor.stream({"input": augmented}):
                # LangChain may yield dicts with "output"/"answer" or objects with .content
                piece = ""
                if isinstance(chunk, dict):
                    piece = chunk.get("output") or chunk.get("answer") or ""
                else:
                    piece = getattr(chunk, "content", "")
                if piece:
                    buf.append(piece)
                    if on_token:
                        with contextlib.suppress(
                            Exception
                        ):  # Don't let UI callback errors kill the agent
                            on_token(piece)
            content = "".join(buf)
        else:
            resp = executor.invoke({"input": augmented})
            content = resp.get("output", "") if isinstance(resp, dict) else str(resp)
    except Exception as e:
        return {"content": f"Error while running agent: {e}", "data": None}

    payload = _select_data_payload(state)
    return {"content": content, "data": payload}
