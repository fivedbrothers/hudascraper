import json
import logging
import pathlib
import re
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel

from hudascraper import Config, GenericScraper, MsSsoAuth, coerce_nested

DATA_DIR = pathlib.Path("./.data")
DATA_DIR.mkdir(exist_ok=True)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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

    # For API-invoked runs we should not open a headed browser by default
    # (that would block the server waiting for manual interaction). Force
    # headless execution unless the caller explicitly requests otherwise.
    try:
        cfg.headless = True
        if getattr(cfg, "session", None) is not None:
            cfg.session.headed_on_first_run = False
    except Exception:
        logger.debug("Could not enforce headless/session flags on cfg")
    logger.debug(
        "scrape: effective headless=%s headed_on_first_run=%s",
        getattr(cfg, "headless", None),
        getattr(getattr(cfg, "session", None), "headed_on_first_run", None),
    )

    # 4) Run scraper
    auth = MsSsoAuth(user, pw) if user and pw else None
    scraper = GenericScraper(cfg, auth)
    try:
        dframe = scraper.run()
    finally:
        scraper.close()

    # 5) Persist results
    # Create a human-readable run directory name in the requested format:
    # {<date>-<time>-<session.site_host>-<session.user>}
    now = datetime.now(tz=UTC)
    date_part = now.strftime("%Y-%m-%d")
    time_part = now.strftime("%H%M%S")

    # Derive a filesystem-safe host label from the base_url when available
    try:
        host = urlparse(cfg.base_url).hostname or "site"
    except (AttributeError, ValueError, TypeError):
        host = "site"
    host_label = re.sub(r"[^A-Za-z0-9]+", "-", host).strip("-") or "site"

    # Username label (from request) or anonymous
    user_label = re.sub(r"[^A-Za-z0-9]+", "-", (user or "anon")).strip("-")

    run_id = f"{date_part}-{time_part}-{host_label}-{user_label}"
    run_dir = DATA_DIR / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Failed to create run directory %s", run_dir)
        raise HTTPException(500, "Failed to create run directory") from None

    try:
        with (run_dir / "result.jsonl").open("w", encoding="utf-8") as outf:
            for _, row in dframe.iterrows():
                outf.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed to write result.jsonl in %s", run_dir)
        raise HTTPException(500, "Failed to persist results") from None

    meta = {
        "run_id": run_id,
        "rows": len(dframe),
        "cols": len(dframe.columns),
        "page_count": dframe.attrs.get("page_count", "?"),
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
    try:
        with (run_dir / "meta.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f)
    except OSError:
        logger.exception("Failed to write meta.json in %s", run_dir)
        raise HTTPException(500, "Failed to persist metadata") from None

    return {"run_id": run_id, "rows": len(dframe)}


@server.get("/results/{run_id}")
def get_results(run_id: str):
    run_dir = DATA_DIR / run_id
    if not run_dir.exists():
        raise HTTPException(404, "Run not found")
    with (run_dir / "meta.json").open(encoding="utf-8") as f:
        meta = json.load(f)
    items = []
    try:
        with (run_dir / "result.jsonl").open(encoding="utf-8") as f:
            for line in f:
                items.append(json.loads(line))
    except OSError:
        logger.exception("Failed to read results for %s", run_id)
        raise HTTPException(500, "Failed to read results") from None
    return {"meta": meta, "items": items}
