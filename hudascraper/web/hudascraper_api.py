import json
import pathlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel

from hudascraper import Config, GenericScraper, MsSsoAuth, coerce_nested

DATA_DIR = pathlib.Path("./.data")
DATA_DIR.mkdir(exist_ok=True)


class ScrapeRequest(BaseModel):
    config: dict[str, Any]
    username: str = ""
    password: str = ""


server = FastAPI()


@server.post("/scrape")
def scrape(
    body: Annotated[
        dict[str, Any],
        Body(description="Either {'config': {...}} or the config object itself"),
    ] = ...,
    username: Annotated[str, Query(description="Optional credential override")] = "",
    password: Annotated[str, Query(description="Optional credential override")] = "",
):
    # 1) Detect payload shape
    raw_config: dict[str, Any] = body.get("config", body)
    # 2) Credentials can be placed either in body or query; query overrides body
    body_user = body.get("username", "")
    body_pass = body.get("password", "")
    user = username or body_user or ""
    pw = password or body_pass or ""

    # 3) Coerce into dataclasses
    cfg = coerce_nested(raw_config, Config)

    # 4) Run scraper
    auth = MsSsoAuth(user, pw) if user and pw else None
    scraper = GenericScraper(cfg, auth)
    try:
        dframe = scraper.run()
    finally:
        scraper.close()

    # 5) Persist results
    run_id = str(int(datetime.now(tz=UTC).timestamp()))
    run_dir = DATA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with Path.open(run_dir / "result.jsonl", "w", encoding="utf-8") as f:
        f.writelines(
            json.dumps(row.to_dict(), ensure_ascii=False) + "\n"
            for _, row in dframe.iterrows()
        )

    with Path.open(run_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "run_id": run_id,
                "rows": len(dframe),
                "cols": len(dframe.columns),
                "page_count": dframe.attrs.get("page_count", "?"),
                "timestamp": datetime.now(tz=UTC).isoformat(),
            },
            f,
        )

    return {"run_id": run_id, "rows": len(dframe)}


@server.get("/results/{run_id}")
def get_results(run_id: str):
    run_dir = DATA_DIR / run_id
    if not run_dir.exists():
        raise HTTPException(404, "Run not found")
    with open(run_dir / "meta.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    items = []
    with open(run_dir / "result.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            items.append(json.loads(line))
    return {"meta": meta, "items": items}
