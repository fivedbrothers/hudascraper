# agent/tools.py
# Tools that the agent uses. Updated to import Path and remain concise.

import json
from pathlib import Path
from typing import Any

import pandas as pd
from scraping.config import ScraperConfig
from scraping.extractor import PlaywrightScraper


def _parse_args(args: Any) -> dict:
    if args is None:
        return {}
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            return {}
    if isinstance(args, dict):
        return args
    return {}

def tool_extract_all_pages(state, args):
    """
    Args JSON: { 'scraper_config': {...}, 'rows_per_page': 100 }
    """
    params = _parse_args(args)
    cfg = ScraperConfig.from_json_dict(params.get("scraper_config", {}))
    rpp = int(params.get("rows_per_page", 100))

    scraper = PlaywrightScraper(cfg)
    try:
        df = scraper.extract_all_pages(rows_per_page=rpp)
    finally:
        scraper.close()

    df.columns = [str(c) for c in df.columns]
    state["df"] = df

    cols = ", ".join(df.columns.tolist()[:20])
    return f"Extracted {len(df):,} rows across {df.attrs.get('page_count', 'unknown')} pages. Columns: {cols}"

def tool_data_profile(state):
    df: pd.DataFrame = state.get("df")
    if df is None or df.empty:
        return "No dataset in memory. Please extract first."

    dtypes = df.dtypes.astype(str).to_dict()
    nulls = df.isna().sum().to_dict()

    num = df.select_dtypes(include="number")
    num_stats = {}
    if not num.empty:
        desc = num.describe().T[["count", "mean", "std", "min", "25%", "50%", "75%", "max"]]
        num_stats = desc.round(3).to_dict(orient="index")

    cat = df.select_dtypes(include="object")
    topk = {}
    if not cat.empty:
        for c in cat.columns:
            vc = df[c].value_counts(dropna=True).head(10)
            topk[c] = vc.to_dict()

    summary = {
        "rows": len(df),
        "columns": list(df.columns),
        "dtypes": dtypes,
        "null_counts": nulls,
        "numeric_stats": num_stats,
        "top_categories": topk,
    }
    return json.dumps(summary, indent=2)

def tool_preview_rows(state, args):
    params = _parse_args(args)
    n = int(params.get("n", 20))
    df: pd.DataFrame = state.get("df")
    if df is None or df.empty:
        return "No dataset in memory. Please extract first."
    return df.head(n).to_markdown(index=False)

def tool_filter_rows(state, args):
    params = _parse_args(args)
    query = params.get("query", "")
    n = int(params.get("n", 20))
    df: pd.DataFrame = state.get("df")
    if df is None or df.empty:
        return "No dataset in memory. Please extract first."
    if not query:
        return "Provide a 'query' expression to filter."
    try:
        filtered = df.query(query)
    except Exception as e:
        return f"Query error: {e}"
    state["df_filtered"] = filtered
    return f"Filtered rows: {len(filtered)}\n\n" + filtered.head(n).to_markdown(index=False)

def tool_save_csv(state, args):
    params = _parse_args(args)
    path = params.get("path")
    df: pd.DataFrame = state.get("df")
    if df is None or df.empty:
        return "No dataset in memory. Please extract first."
    if not path:
        return "Provide 'path' to save."
    p = Path(str(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return f"Saved {len(df)} rows to {p}"
