#!/usr/bin/env python3
"""
Backfill price_history from TCGCSV's daily archive (2026-08-05).

WHY: our price_history started 2026-04-01 (126 days). TCGCSV publishes a daily
archive back to ~2024-02-08 at

    https://tcgcsv.com/archive/tcgplayer/prices-YYYY-MM-DD.ppmd.7z

which extracts to {date}/{categoryId}/{groupId}/prices — the SAME layout and
JSON shape (`results` array) that scripts/import_to_sqlite.py already walks.
So ~2.5 years of history is recoverable from the source we already use, for
the cost of bandwidth. Deeper history is what conformal calibration, honest
long horizons, and real backtests need.

WHY A SEPARATE SCRIPT rather than reusing import_to_sqlite.py: that importer
deliberately only ingests date dirs NEWER than MAX(date) (`d.name > max_date`),
so it skips every historical date by design. Its parse/filter logic is mirrored
here verbatim — if you change the filters there, change them here.

SAFETY RAILS (this writes to the production DB the live oracle reads):
  * NEVER writes a date >= the current MAX(date). Rows dated later than the
    TCGCSV max date shift MAX(date) forward, and search/market resolve prices
    via `p.date = MAX(date)` — that would zero out prices for every normal
    card. This is the documented MAX(date) landmine; the guard is unconditional.
  * price_history has NO unique constraint, so a re-run would silently double
    rows. Every date is skipped if it already has ANY rows. That also makes the
    job resumable: re-run after an interruption and it continues where it left off.
  * One transaction per day — short write locks, WAL-friendly, so the live
    oracle keeps serving throughout.
  * Additive only. Rollback is exactly:
        DELETE FROM price_history WHERE date < '<first date we had>';
  * 404s (archive gaps) are logged and skipped, never fatal.

USAGE
    python3 backfill_tcgcsv_history.py --start 2024-02-08 --end 2026-03-31
    python3 backfill_tcgcsv_history.py --start ... --end ... --dry-run
    python3 backfill_tcgcsv_history.py --start ... --end ... --limit 5
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

DB_PATH = os.path.expanduser("~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite")
ARCHIVE = "https://tcgcsv.com/archive/tcgplayer/prices-{d}.ppmd.7z"
SEVENZ = shutil.which("7z") or shutil.which("7zz") or "/opt/homebrew/bin/7z"
UA = {"User-Agent": "undesirables-oracle-backfill/1.0 (+https://oracle.the-undesirables.com)"}

# Mirrors import_to_sqlite.py exactly. Keep in sync.
OK_SUBTYPES = ("Normal", "Holofoil", "Unlimited", "")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def parse_day(root: Path, date_str: str):
    """Walk {date}/{cat}/{group}/prices and return insertable rows.
    Filter logic mirrored verbatim from import_to_sqlite.import_price_history."""
    rows = []
    for prices_file in root.rglob("prices"):
        try:
            content = prices_file.read_text(encoding="utf-8", errors="ignore")
            if content.strip().startswith("[") or content.strip().startswith("{"):
                data = json.loads(content)
                records = data if isinstance(data, list) else data.get("results", [])
            else:
                import csv, io
                records = list(csv.DictReader(io.StringIO(content)))
        except Exception:
            continue
        for row in records:
            try:
                pid = int(row.get("productId", 0))
                mp_raw = row.get("marketPrice")
                if mp_raw is None or mp_raw == "":
                    continue
                mp = float(mp_raw)
                if pid <= 0 or mp <= 0:
                    continue
                sub = row.get("subTypeName", "") or ""
                if sub and sub not in OK_SUBTYPES:
                    continue
                rows.append((pid, mp,
                             float(row.get("lowPrice", 0) or 0),
                             float(row.get("midPrice", 0) or 0),
                             float(row.get("highPrice", 0) or 0),
                             date_str, sub))
            except (ValueError, TypeError):
                continue
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="stop after N days imported")
    # Newest-first is the default for a reason: our own history starts at the
    # END of this range, so walking backward keeps the corpus CONTIGUOUS at
    # every moment. Interrupt a forward run and you get a hole between where it
    # stopped and where our data begins — and a hole is worse than a shorter
    # history for anything fitting on a continuous series.
    ap.add_argument("--oldest-first", action="store_true",
                    help="walk forward instead (leaves a gap if interrupted)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")

    db_max = conn.execute(
        "SELECT MAX(date) FROM price_history WHERE product_id < 9500000").fetchone()[0]
    log(f"DB max date = {db_max} (nothing on/after this will be written)")

    have = {r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM price_history WHERE product_id < 9500000")}
    log(f"DB already has {len(have)} distinct dates")

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    days = list(daterange(start, end))
    if not args.oldest_first:
        days.reverse()
    log(f"walking {len(days)} day(s) {'oldest' if args.oldest_first else 'NEWEST'}-first")
    imported = total_rows = skipped = missing = 0

    for d in days:
        ds = d.isoformat()

        # RAIL 1: never touch the present. Unconditional.
        if db_max and ds >= db_max:
            log(f"{ds}: SKIP — at/after DB max date ({db_max}); refusing (MAX(date) landmine)")
            skipped += 1
            continue
        # RAIL 2: idempotency — no unique constraint exists to save us.
        if ds in have:
            skipped += 1
            continue

        url = ARCHIVE.format(d=ds)
        tmp = Path(tempfile.mkdtemp(prefix=f"tcgcsv-{ds}-"))
        try:
            arc = tmp / "day.7z"
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=180) as r, open(arc, "wb") as f:
                    shutil.copyfileobj(r, f)
            except Exception as e:
                code = getattr(e, "code", None)
                log(f"{ds}: archive unavailable ({code or type(e).__name__}) — skipping")
                missing += 1
                continue

            p = subprocess.run([SEVENZ, "x", "-y", f"-o{tmp}", str(arc)],
                               capture_output=True, text=True)
            if p.returncode != 0:
                log(f"{ds}: extract failed ({p.stderr[:80]}) — skipping")
                missing += 1
                continue

            rows = parse_day(tmp, ds)
            if not rows:
                log(f"{ds}: no usable rows — skipping")
                missing += 1
                continue

            if args.dry_run:
                log(f"{ds}: DRY-RUN would insert {len(rows):,} rows")
            else:
                conn.executemany(
                    "INSERT INTO price_history "
                    "(product_id, market_price, low_price, mid_price, high_price, date, sub_type) "
                    "VALUES (?,?,?,?,?,?,?)", rows)
                conn.commit()          # per-day commit: short lock, live oracle unaffected
                log(f"{ds}: +{len(rows):,} rows")

            imported += 1
            total_rows += len(rows)
            if args.limit and imported >= args.limit:
                log(f"--limit {args.limit} reached; stopping")
                break
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    log(f"DONE — days imported {imported}, rows {total_rows:,}, "
        f"skipped {skipped}, unavailable {missing}")
    conn.close()


if __name__ == "__main__":
    main()
