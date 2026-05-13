#!/usr/bin/env python3
"""
Sync SQLite data → Vercel KV (Upstash Redis)

Reads shroomy_stats and cards from market_memory.sqlite
and pushes to Upstash KV via the REST pipeline API.

Uses large pipeline batches (500 cmds/call) to minimize API request count.
Upstash free tier = 500K commands/month. Each pipeline call = 1 command.
With 190K stats + 3K name prefixes, total API calls ≈ 400.

Key schema:
  tcg:stats:{product_id} → {lastPrice, drift, volatility}
  tcg:names:{prefix}     → [{id, n, c}, ...]  (3-char prefix name index)
  tcg:meta                → {updated, productCount, cardsCount, dateRange}

Env vars (checks both naming conventions):
  KV_REST_API_URL / UPSTASH_REDIS_REST_URL
  KV_REST_API_TOKEN / UPSTASH_REDIS_REST_TOKEN
"""

import os
import sys
import json
import sqlite3
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

try:
    import requests
except ImportError:
    print("❌ requests not installed. Run: pip3 install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="[KV Sync] %(message)s")
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────
WORK_DIR = Path(os.environ.get("CI_PROJECT_DIR", Path(__file__).parent.parent))
DB_PATH = WORK_DIR / ".cache" / "market_memory.sqlite"

# Support both env var naming conventions
KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")

BATCH_SIZE = 500       # 500 commands per pipeline = 1 API call (saves monthly quota)
KEY_TTL = 60 * 60 * 24 * 10  # 10 days TTL — refreshed by daily cron


def pipeline(commands: list[list]) -> list:
    """Execute a pipeline batch. Counts as 1 command toward monthly limit."""
    resp = requests.post(
        f"{KV_URL}/pipeline",
        headers={"Authorization": f"Bearer {KV_TOKEN}", "Content-Type": "application/json"},
        json=commands,
        timeout=60,
    )
    if resp.status_code != 200:
        logger.error(f"Pipeline error {resp.status_code}: {resp.text[:300]}")
        resp.raise_for_status()
    results = resp.json()
    errors = [r for r in results if isinstance(r, dict) and "error" in r]
    if errors:
        logger.warning(f"  Redis errors ({len(errors)}): {errors[0]}")
    return results


def sync_stats(conn) -> int:
    """Push shroomy_stats to KV."""
    rows = conn.execute(
        "SELECT product_id, last_price, drift, volatility FROM shroomy_stats WHERE last_price > 0"
    ).fetchall()
    logger.info(f"Syncing {len(rows):,} stats entries...")

    commands = []
    synced = 0
    api_calls = 0

    for pid, price, drift, vol in rows:
        value = json.dumps({
            "lastPrice": round(price, 4),
            "drift": round(drift, 8),
            "volatility": round(vol, 8),
        })
        commands.append(["SET", f"tcg:stats:{pid}", value, "EX", str(KEY_TTL)])

        if len(commands) >= BATCH_SIZE:
            pipeline(commands)
            synced += len(commands)
            api_calls += 1
            commands = []
            if synced % 50000 < BATCH_SIZE:
                logger.info(f"  Stats: {synced:,}/{len(rows):,} ({api_calls} API calls)")

    if commands:
        pipeline(commands)
        synced += len(commands)
        api_calls += 1

    logger.info(f"✅ Stats: {synced:,} keys in {api_calls} API calls")
    return synced


def sync_names(conn) -> int:
    """Push card name index as 3-char prefix keys."""
    cards = conn.execute(
        "SELECT product_id, name, clean_name, category_id FROM cards WHERE name != ''"
    ).fetchall()

    prefix_map = defaultdict(list)
    for pid, name, clean_name, cat_id in cards:
        if not name:
            continue
        key = (clean_name or name)[:3].lower().strip()
        if len(key) < 2:
            continue
        prefix_map[key].append({"id": pid, "n": name, "c": cat_id})

    logger.info(f"Syncing {len(prefix_map):,} name prefixes (covering {len(cards):,} cards)...")

    commands = []
    synced = 0
    api_calls = 0

    for prefix, entries in prefix_map.items():
        commands.append(["SET", f"tcg:names:{prefix}", json.dumps(entries), "EX", str(KEY_TTL)])
        if len(commands) >= BATCH_SIZE:
            pipeline(commands)
            synced += len(commands)
            api_calls += 1
            commands = []

    if commands:
        pipeline(commands)
        synced += len(commands)
        api_calls += 1

    logger.info(f"✅ Names: {synced:,} prefix keys in {api_calls} API calls")
    return synced


def sync_history(conn, max_products=50000) -> int:
    """Push daily price time-series for top products to KV.

    Filters to products with market_price > $0.50 and 3+ data points.
    Uses pipeline batching (500/call) to minimize API request count.
    50K products / 500 per batch = ~100 API calls.
    """
    # Get top products by value that have meaningful history
    products = conn.execute("""
        SELECT product_id, COUNT(*) as days, MAX(market_price) as max_price
        FROM price_history
        WHERE market_price > 0.50
        GROUP BY product_id
        HAVING days >= 3
        ORDER BY max_price DESC
        LIMIT ?
    """, (max_products,)).fetchall()
    logger.info(f"Syncing history for {len(products):,} products (price>$0.50, 3+ days)...")

    # Pre-fetch all history for these products in one query (much faster)
    product_ids = [str(p[0]) for p in products]
    product_set = set(int(pid) for pid in product_ids)

    # Build history dict: {product_id: [{date, price}, ...]}
    history_map = defaultdict(list)
    cursor = conn.execute(
        f"SELECT product_id, date, market_price FROM price_history "
        f"WHERE product_id IN ({','.join('?' * len(product_ids))}) AND market_price > 0 "
        f"ORDER BY product_id, date",
        product_ids
    )
    for pid, date_str, price in cursor:
        history_map[pid].append({"date": date_str, "price": round(price, 2)})

    # Pipeline batch the SET commands
    HISTORY_TTL = str(60 * 60 * 48)  # 48h TTL
    commands = []
    synced = 0
    api_calls = 0

    for pid in product_set:
        entries = history_map.get(pid)
        if not entries:
            continue
        commands.append(["SET", f"tcg:history:{pid}", json.dumps(entries), "EX", HISTORY_TTL])

        if len(commands) >= BATCH_SIZE:
            pipeline(commands)
            synced += len(commands)
            api_calls += 1
            commands = []
            if synced % 10000 < BATCH_SIZE:
                logger.info(f"  History: {synced:,}/{len(products):,} ({api_calls} API calls)")

    if commands:
        pipeline(commands)
        synced += len(commands)
        api_calls += 1

    logger.info(f"✅ History: {synced:,} product keys in {api_calls} API calls")
    return synced


def main():
    if not KV_URL or not KV_TOKEN:
        logger.error("❌ Set KV_REST_API_URL or UPSTASH_REDIS_REST_URL environment variable")
        logger.error("   and KV_REST_API_TOKEN or UPSTASH_REDIS_REST_TOKEN")
        sys.exit(1)

    if not DB_PATH.exists():
        logger.error(f"❌ Database not found: {DB_PATH}")
        sys.exit(1)

    logger.info(f"Opening database: {DB_PATH}")
    logger.info(f"Target KV: {KV_URL}")
    conn = sqlite3.connect(str(DB_PATH))

    # Verify data
    stats_count = conn.execute("SELECT COUNT(*) FROM shroomy_stats").fetchone()[0]
    cards_count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    date_range = conn.execute("SELECT MIN(date), MAX(date) FROM price_history").fetchone()
    logger.info(f"Database: {stats_count:,} stats, {cards_count:,} cards, dates {date_range[0]}→{date_range[1]}")

    if stats_count == 0:
        logger.error("❌ No stats data. Run import_to_sqlite.py first.")
        sys.exit(1)

    # Sync
    t0 = time.time()
    synced_stats = sync_stats(conn)
    synced_names = sync_names(conn)
    synced_history = sync_history(conn)

    # Meta
    meta = json.dumps({
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "productCount": stats_count,
        "cardsCount": cards_count,
        "historyProducts": synced_history,
        "dateRange": {"min": date_range[0] or "", "max": date_range[1] or ""},
        "source": "market_memory.sqlite",
    })
    pipeline([["SET", "tcg:meta", meta, "EX", str(KEY_TTL)]])

    elapsed = time.time() - t0
    conn.close()

    logger.info(f"── Sync Complete ({elapsed:.0f}s) ──")
    logger.info(f"  Stats: {synced_stats:,}")
    logger.info(f"  Names: {synced_names:,}")
    logger.info(f"  History: {synced_history:,}")
    logger.info(f"  Date range: {date_range[0]} → {date_range[1]}")
    logger.info(f"✅ All data live on Vercel KV")


if __name__ == "__main__":
    main()
