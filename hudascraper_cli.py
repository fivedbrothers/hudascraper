import argparse
import logging
from pathlib import Path

from hudascraper import GenericScraper, MsSsoAuth, load_config

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", type=str, required=True, help="Path to selectors JSON")
    ap.add_argument("--csv", type=str, default="", help="Optional path to export CSV")
    ap.add_argument("--usr", help="Session username (for session keying)")
    ap.add_argument("--ms-username")
    ap.add_argument("--ms-password")
    args = ap.parse_args()

    cfg = load_config(args.cfg)

    if args.usr:
        cfg.session.user = args.usr

    auth = None
    if args.ms_username and args.ms_password:
        auth = MsSsoAuth(args.ms_username, args.ms_password)

    scraper = GenericScraper(cfg=cfg, auth=auth)

    try:
        dframe = scraper.run()
    finally:
        scraper.close()

    logger.info(
        "Rows: %s | Cols: %s | Pages: %s",
        len(dframe),
        len(dframe.columns),
        dframe.attrs.get("page_count"),
    )
    logger.info("\n%s", dframe.head(10).to_string(index=False))

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        dframe.to_csv(out, index=False, encoding="utf-8")
        logger.info("Saved CSV to: %s", out)


if __name__ == "__main__":
    main()
