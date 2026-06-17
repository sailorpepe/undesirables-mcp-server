#!/usr/bin/env python3
"""
enrich_subtype.py — Backfill price_history.sub_type from the on-disk archives.

A single product can have multiple printings on the same date (e.g. Normal +
Holofoil) at very different prices. The importer kept both rows but discarded
the subTypeName, so they were indistinguishable. This walks every date in
tmp_history/, reads each prices file, and labels each price row by matching
(product_id, date, market_price) back to the archive's subTypeName.

Non-destructive: only fills sub_type where it is still NULL (idempotent /
resumable). Uses the SAME subtype filter as import_to_sqlite.py so excluded
printings (e.g. Reverse Holofoil) can never mislabel a kept row.
"""
import os, sys, json, csv, io, sqlite3, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[subtype] %(message)s")
log = logging.getLogger(__name__)

WORK_DIR = Path(os.environ.get("CI_PROJECT_DIR", Path(__file__).parent.parent))
DB_PATH = WORK_DIR / ".cache" / "market_memory.sqlite"
HISTORY_DIR = WORK_DIR / "tmp_history"

# Same set the importer keeps — anything else was never inserted, so never label it.
KEEP = ("Normal", "Holofoil", "Unlimited", "")


def records(prices_file):
    content = prices_file.read_text(encoding="utf-8", errors="ignore")
    s = content.strip()
    if s.startswith("[") or s.startswith("{"):
        data = json.loads(content)
        return data if isinstance(data, list) else data.get("results", [])
    return list(csv.DictReader(io.StringIO(content)))


def main():
    if not HISTORY_DIR.exists():
        log.error(f"History dir not found: {HISTORY_DIR}"); return 1
    conn = sqlite3.connect(str(DB_PATH))

    date_dirs = sorted(d for d in HISTORY_DIR.iterdir()
                       if d.is_dir() and len(d.name) == 10)
    start = conn.execute(
        "SELECT COUNT(*) FROM price_history WHERE sub_type IS NOT NULL").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    log.info(f"{len(date_dirs)} dates. Labeled at start: {start:,}/{total:,}")

    for di, date_dir in enumerate(date_dirs, 1):
        date_str = date_dir.name
        updates = []
        for pf in date_dir.rglob("prices"):
            try:
                recs = records(pf)
            except Exception:
                continue
            for r in recs:
                sub = r.get("subTypeName", "") or ""
                if sub not in KEEP:
                    continue
                try:
                    pid = int(r.get("productId", 0))
                    mp = r.get("marketPrice")
                    if pid <= 0 or mp in (None, ""):
                        continue
                    mp = float(mp)
                    if mp <= 0:
                        continue
                except (ValueError, TypeError):
                    continue
                updates.append((sub, pid, date_str, mp))

        if updates:
            conn.executemany(
                "UPDATE price_history SET sub_type=? "
                "WHERE product_id=? AND date=? AND market_price=? AND sub_type IS NULL",
                updates)
            conn.commit()
        labeled = conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE sub_type IS NOT NULL").fetchone()[0]
        log.info(f"  [{di}/{len(date_dirs)}] {date_str}: {len(updates):,} recs | labeled total {labeled:,}")

    labeled = conn.execute(
        "SELECT COUNT(*) FROM price_history WHERE sub_type IS NOT NULL").fetchone()[0]
    log.info(f"DONE. {labeled:,}/{total:,} rows labeled (+{labeled-start:,}).")
    # Breakdown
    for st, n in conn.execute(
        "SELECT COALESCE(sub_type,'(null)'), COUNT(*) FROM price_history "
        "GROUP BY sub_type ORDER BY COUNT(*) DESC").fetchall():
        log.info(f"    {st or '(empty)'}: {n:,}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
