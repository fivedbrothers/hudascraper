"""
Rename existing run directories in .data from the old format.

20250823T132536218041Z_practice-expandtesting-com_anon
to the new format:
{<date>-<time>-<session.site_host>-<session.user>}

Run: python scripts/rename_run_dirs.py
"""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATA_DIR = Path(".data")
if not DATA_DIR.exists():
    logger.info("No .data directory found; nothing to do.")
    raise SystemExit(0)

pattern = re.compile(r"^(?P<ts>\d{8}T\d{6}\d+Z)_(?P<host>[^_]+)_(?P<user>.+)$")

mappings = []
for p in sorted(DATA_DIR.iterdir()):
    if not p.is_dir():
        continue
    m = pattern.match(p.name)
    if not m:
        continue
    ts = m.group("ts")
    host = m.group("host")
    user = m.group("user")
    try:
        dt = datetime.strptime(ts, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
    except ValueError as e:
        logger.warning("Skipping %s: failed to parse timestamp: %s", p.name, e)
        continue
    date_part = dt.strftime("%Y-%m-%d")
    time_part = dt.strftime("%H%M%S")
    new_name = f"{date_part}-{time_part}-{host}-{user}"
    target = DATA_DIR / new_name
    # avoid clobbering
    suffix = 1
    while target.exists():
        target = DATA_DIR / f"{new_name}-{suffix}"
        suffix += 1
    try:
        p.rename(target)
        mappings.append((p.name, target.name))
    except OSError:
        logger.exception(
            "Failed to rename %s -> %s due to OS error", p.name, target.name
        )

if not mappings:
    logger.info("No directories matched the old pattern; nothing to rename.")
else:
    logger.info("Renamed directories:")
    for a, b in mappings:
        logger.info("  %s -> %s", a, b)

# List resulting .data contents
logger.info("\nCurrent .data contents:")
for p in sorted(DATA_DIR.iterdir()):
    logger.info("  %s", p.name)
