# (Reserved for future persistence layers beyond CSV: parquet, sqlite, etc.)
# This module is intentionally minimal to keep responsibilities clear.

from pathlib import Path

import pandas as pd


def save_csv(df: pd.DataFrame, path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return str(p)
