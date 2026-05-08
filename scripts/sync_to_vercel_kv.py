#!/usr/bin/env python3
"""
TCG Oracle → Vercel KV Sync

Reads from local market_memory.sqlite and pushes price history + stats
to Vercel KV so the /api/v1/history endpoint can serve it.

Run after tcg_cron.py + import_to_sqlite.py on the Mac Mini:
  python3 scripts/sync_to_vercel_kv.py

Requires:
  pip install requests
  
Environment:
  KV_REST_API_URL   — Vercel KV REST endpoint (from Vercel dashboard)
  KV_REST_API_TOKEN — Vercel KV REST token
"""

import os
import sys
import json
import sqlite3
import logging
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="[KV Sync] %(message)s")
logger = logging.getLogger(__name__)

WORK_DIR = Path(os.environ.get("CI_PROJECT_DIR", Path(__file__).parent.parent))
DB_PATH = WORK_DIR / ".cache" / "market_memory.sqlite"

# Vercel KV REST API credentials
KV_URL = os.environ.get("KV_REST_API_URL", "")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")

# Batch size for KV pipeline operations
BATCH_SIZE = 50

# Only sync products with meaningful history (>= 3 data points)
MIN_HISTORY_POINTS = 3


def kv_pipeline(commands: list) -> bool:
    """Execute a batch of KV commands via the REST pipeline endpoint."""
    if not KV_URL or not KV_TOKEN:
        logger.error("KV_REST_API_URL and KV_REST_API_TOKEN must be set")
        return False
    
    url = f"{KV_URL}/pipeline"
    headers = {
        "Authorization": f"Bearer {KV_TOKEN}",
        "Content-Type": "application/json",
    }
    
    try:
        resp = requests.post(url, json=commands, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"KV pipeline error: {resp.status_code} — {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"KV request failed: {e}")
        return False


def sync_stats(conn):
    """Push shroomy_stats to KV as individual keys."""
    cursor = conn.execute("""
        SELECT product_id, last_price, drift, volatility
        FROM shroomy_stats
        WHERE last_price > 0
        ORDER BY last_price DESC
    """)
    
    rows = cursor.fetchall()
    logger.info(f"Syncing {len(rows):,} product stats to KV...")
    
    commands = []
    synced = 0
    
    for pid, last_price, drift, volatility in rows:
        value = json.dumps({
            "lastPrice": last_price,
            "drift": drift,
            "volatility": volatility,
        })
        # SET key value EX 86400 (expire in 24h to auto-cleanup stale data)
        commands.append(["SET", f"tcg:stats:{pid}", value, "EX", 86400])
        
        if len(commands) >= BATCH_SIZE:
            if kv_pipeline(commands):
                synced += len(commands)
            commands = []
            time.sleep(0.1)  # Rate limit
    
    # Flush remaining
    if commands:
        if kv_pipeline(commands):
            synced += len(commands)
    
    logger.info(f"✅ Synced {synced:,} stats to KV")
    return synced


def sync_history(conn):
    """Push price_history time series to KV."""
    # Find products with sufficient history
    cursor = conn.execute("""
        SELECT product_id, COUNT(*) as cnt
        FROM price_history
        GROUP BY product_id
        HAVING cnt >= ?
        ORDER BY cnt DESC
    """, (MIN_HISTORY_POINTS,))
    
    product_ids = cursor.fetchall()
    logger.info(f"Found {len(product_ids):,} products with {MIN_HISTORY_POINTS}+ history points")
    
    commands = []
    synced = 0
    
    for pid, count in product_ids:
        # Get the full time series for this product
        hist_cursor = conn.execute("""
            SELECT date, market_price, low_price, high_price
            FROM price_history
            WHERE product_id = ?
            ORDER BY date ASC
        """, (pid,))
        
        history = [
            {"date": row[0], "price": row[1], "low": row[2], "high": row[3]}
            for row in hist_cursor.fetchall()
        ]
        
        value = json.dumps(history)
        commands.append(["SET", f"tcg:history:{pid}", value, "EX", 86400])
        
        if len(commands) >= BATCH_SIZE:
            if kv_pipeline(commands):
                synced += len(commands)
            commands = []
            time.sleep(0.1)
    
    if commands:
        if kv_pipeline(commands):
            synced += len(commands)
    
    logger.info(f"✅ Synced {synced:,} product histories to KV")
    return synced


def sync_catalog_index(conn):
    """Push a name → product_id search index to KV."""
    # Get top products by price (most likely to be searched)
    cursor = conn.execute("""
        SELECT s.product_id, c.name, c.clean_name, c.category_id
        FROM shroomy_stats s
        LEFT JOIN cards c ON s.product_id = c.product_id
        WHERE s.last_price > 1.0
        ORDER BY s.last_price DESC
        LIMIT 10000
    """)
    
    index = {}
    for pid, name, clean_name, cat_id in cursor.fetchall():
        display_name = clean_name or name or f"Product #{pid}"
        index[display_name] = {
            "product_id": pid,
            "category_id": cat_id,
        }
    
    if index:
        value = json.dumps(index)
        commands = [["SET", "tcg:name_index", value, "EX", 86400]]
        if kv_pipeline(commands):
            logger.info(f"✅ Synced name index with {len(index):,} entries")
    
    # Set last sync timestamp
    from datetime import datetime
    kv_pipeline([["SET", "tcg:last_sync", datetime.now().isoformat()]])


def main():
    if not KV_URL or not KV_TOKEN:
        logger.error("Missing environment variables:")
        logger.error("  KV_REST_API_URL  — from Vercel dashboard → Storage → KV → .env.local")
        logger.error("  KV_REST_API_TOKEN — from the same location")
        logger.error("")
        logger.error("Export them before running:")
        logger.error("  export KV_REST_API_URL='https://your-kv.kv.vercel-storage.com'")
        logger.error("  export KV_REST_API_TOKEN='your-token-here'")
        sys.exit(1)
    
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        logger.error("Run tcg_cron.py + import_to_sqlite.py first")
        sys.exit(1)
    
    logger.info(f"Opening database: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    
    stats_synced = sync_stats(conn)
    history_synced = sync_history(conn)
    sync_catalog_index(conn)
    
    conn.close()
    
    logger.info(f"── Sync Complete ──")
    logger.info(f"  Stats synced:   {stats_synced:,}")
    logger.info(f"  History synced: {history_synced:,}")


if __name__ == "__main__":
    main()
