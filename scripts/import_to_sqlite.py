#!/usr/bin/env python3
"""
Import pipeline: tcg_stats.json + raw TCGCSV archives → market_memory.sqlite

This script replaces the Nuitka-compiled tcg_oracle.import_shroomy_dataset()
function, which requires Python 3.13. It performs two critical updates:

1. Imports drift/volatility/lastPrice from data/tcg_stats.json → shroomy_stats table
2. Imports raw daily prices from tmp_history/ archives → price_history table

Run after tcg_cron.py to keep market_memory.sqlite fresh.
"""

import os
import sys
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="[SQLite Import] %(message)s")
logger = logging.getLogger(__name__)

WORK_DIR = Path(os.environ.get("CI_PROJECT_DIR", Path(__file__).parent.parent))
CACHE_DIR = WORK_DIR / ".cache"
DB_PATH = CACHE_DIR / "market_memory.sqlite"
STATS_FILE = WORK_DIR / "data" / "tcg_stats.json"
HISTORY_DIR = WORK_DIR / "tmp_history"


def init_db(conn):
    """Ensure the schema exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            product_id INTEGER PRIMARY KEY,
            name TEXT, clean_name TEXT, rarity TEXT, category_id INTEGER, group_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            product_id INTEGER, market_price REAL, low_price REAL,
            mid_price REAL, high_price REAL, date TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shroomy_stats (
            product_id INTEGER PRIMARY KEY,
            last_price REAL, drift REAL, volatility REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_clean ON cards(clean_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ss_price ON shroomy_stats(last_price)")
    conn.commit()


def import_shroomy_stats(conn):
    """Import drift/volatility from tcg_stats.json into shroomy_stats table."""
    if not STATS_FILE.exists():
        logger.error(f"Stats file not found: {STATS_FILE}")
        return 0

    logger.info(f"Loading {STATS_FILE.name}...")
    stats = json.loads(STATS_FILE.read_text())
    logger.info(f"Loaded {len(stats):,} products from JSON")

    rows = []
    for pid_str, entry in stats.items():
        try:
            pid = int(pid_str)
            last_price = float(entry.get("lastPrice", 0))
            drift = float(entry.get("drift", 0))
            volatility = float(entry.get("volatility", 0))
            if last_price > 0:
                rows.append((pid, last_price, drift, volatility))
        except (ValueError, TypeError):
            continue

    logger.info(f"Upserting {len(rows):,} shroomy_stats rows...")
    conn.executemany(
        "INSERT OR REPLACE INTO shroomy_stats (product_id, last_price, drift, volatility) VALUES (?, ?, ?, ?)",
        rows
    )
    conn.commit()
    logger.info(f"✅ shroomy_stats updated: {len(rows):,} products")
    return len(rows)


def import_price_history(conn):
    """Import raw daily prices from tmp_history/ into price_history table."""
    if not HISTORY_DIR.exists():
        logger.warning(f"History directory not found: {HISTORY_DIR}")
        return 0

    # Get the current max date in the DB to avoid re-importing old data
    cursor = conn.execute("SELECT MAX(date) FROM price_history")
    max_date = cursor.fetchone()[0] or "2000-01-01"
    logger.info(f"Current max date in price_history: {max_date}")

    # Find all date directories newer than max_date
    date_dirs = sorted([
        d for d in HISTORY_DIR.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name > max_date
    ])

    if not date_dirs:
        logger.info("No new dates to import into price_history")
        return 0

    logger.info(f"Found {len(date_dirs)} new date(s) to import: {[d.name for d in date_dirs]}")

    total_rows = 0
    for date_dir in date_dirs:
        date_str = date_dir.name
        rows = []

        # Walk category/group/prices structure
        for prices_file in date_dir.rglob("prices"):
            try:
                content = prices_file.read_text(encoding="utf-8", errors="ignore")
                if content.strip().startswith("[") or content.strip().startswith("{"):
                    data = json.loads(content)
                    records = data if isinstance(data, list) else data.get("results", [])
                else:
                    import csv, io
                    reader = csv.DictReader(io.StringIO(content))
                    records = list(reader)

                for row in records:
                    try:
                        pid = int(row.get("productId", 0))
                        market_price = row.get("marketPrice")
                        if market_price is None or market_price == "":
                            continue
                        mp = float(market_price)
                        if pid <= 0 or mp <= 0:
                            continue

                        # Filter to common sub-types
                        sub = row.get("subTypeName", "")
                        if sub and sub not in ("Normal", "Holofoil", "Unlimited", ""):
                            continue

                        low = float(row.get("lowPrice", 0) or 0)
                        mid = float(row.get("midPrice", 0) or 0)
                        high = float(row.get("highPrice", 0) or 0)
                        rows.append((pid, mp, low, mid, high, date_str))
                    except (ValueError, TypeError):
                        continue
            except Exception as e:
                logger.warning(f"  Failed to parse {prices_file}: {e}")
                continue

        if rows:
            conn.executemany(
                "INSERT INTO price_history (product_id, market_price, low_price, mid_price, high_price, date) VALUES (?, ?, ?, ?, ?, ?)",
                rows
            )
            conn.commit()
            total_rows += len(rows)
            logger.info(f"  {date_str}: imported {len(rows):,} price rows")

    logger.info(f"✅ price_history updated: {total_rows:,} new rows across {len(date_dirs)} day(s)")
    return total_rows


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Opening database: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    init_db(conn)

    stats_count = import_shroomy_stats(conn)
    history_count = import_price_history(conn)

    # Verify
    cursor = conn.execute("SELECT MAX(date) FROM price_history")
    new_max = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM shroomy_stats")
    stats_total = cursor.fetchone()[0]

    conn.close()

    logger.info(f"── Summary ──")
    logger.info(f"  shroomy_stats: {stats_total:,} total products")
    logger.info(f"  price_history max date: {new_max}")
    logger.info(f"  New rows imported: {history_count:,}")
    logger.info(f"Pipeline complete.")


if __name__ == "__main__":
    main()
