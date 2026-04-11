#!/usr/bin/env python3
"""
TCGCSV Daily Snapshot Pipeline — GitLab CI Cron Job
Downloads yesterday's price archive from TCGCSV, extracts target categories,
and computes rolling drift/volatility stats per card.

Ported from Shroomy Simulator (download-tcg-history.ts + import-tcg-csv.ts)
"""

import os
import sys
import json
import math
import time
import logging
import sqlite3
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="[TCG Cron] %(message)s")
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────
DAYS_TO_FETCH = 7           # Daily cron = only need last 7 days (recent fills)
POLITE_DELAY = 3            # Seconds between downloads (respect TCGCSV)
SAFETY_MIN_DAYS = 1         # Abort if fewer than this many days succeed

TARGET_CATEGORIES = [
    1,   # Magic: The Gathering
    2,   # Yu-Gi-Oh!
    3,   # Pokémon
    68,  # One Piece
    71,  # Lorcana
    85,  # Pokémon (Japan)
]

ARCHIVE_URL = "https://tcgcsv.com/archive/tcgplayer/prices-{date}.ppmd.7z"

WORK_DIR = Path(os.environ.get("CI_PROJECT_DIR", Path(__file__).parent.parent))
TEMP_DIR = WORK_DIR / "tmp_archives"
HISTORY_DIR = WORK_DIR / "tmp_history"
OUTPUT_FILE = WORK_DIR / "data" / "tcg_stats.json"


def download_file(url: str, dest: Path) -> bool:
    """Download a file with User-Agent spoofing to avoid 403."""
    logger.info(f"  Downloading {url}...")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                logger.warning(f"  HTTP {resp.status} — skipping")
                return False
            dest.write_bytes(resp.read())
        return True
    except Exception as e:
        logger.warning(f"  Download failed: {e}")
        return False


def extract_categories(archive: Path, output_dir: Path, categories: list[int]):
    """Extract only the target category folders from the 7z archive."""
    wildcards = [f"*/{cat_id}/*" for cat_id in categories]
    cmd = ["7za", "x", str(archive), f"-o{output_dir}", "-y"] + wildcards
    logger.info(f"  Extracting categories {categories}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            # 7za returns 1 for warnings (e.g., no files matched a wildcard)
            if result.returncode > 1:
                logger.warning(f"  7za error (code {result.returncode}): {result.stderr[:200]}")
                return False
        return True
    except FileNotFoundError:
        logger.error("  7za not found! Install p7zip: apt-get install p7zip-full")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("  Extraction timed out")
        return False


def scan_price_files(history_dir: Path) -> dict:
    """
    Recursively scan extracted price files and build per-product history.
    Returns: {product_id: [(date, market_price), ...]}
    """
    history: dict[int, list[tuple[str, float]]] = {}

    for prices_file in history_dir.rglob("prices"):
        # Extract date from path: .../2026-01-15/3/604/prices
        parts = str(prices_file).split(os.sep)
        date_str = None
        for part in parts:
            if len(part) == 10 and part[4] == "-" and part[7] == "-":
                date_str = part
                break

        if not date_str:
            continue

        try:
            content = prices_file.read_text(encoding="utf-8", errors="ignore")
            # Detect JSON vs CSV
            if content.strip().startswith("[") or content.strip().startswith("{"):
                data = json.loads(content)
                records = data if isinstance(data, list) else data.get("results", [])
            else:
                # CSV parse
                import csv
                import io
                reader = csv.DictReader(io.StringIO(content))
                records = list(reader)

            for row in records:
                try:
                    pid = int(row.get("productId", 0))
                    market_price = row.get("marketPrice")
                    if market_price is None or market_price == "":
                        continue
                    price = float(market_price)
                    if pid <= 0 or price <= 0:
                        continue

                    # Filter to common sub-types only
                    sub = row.get("subTypeName", "")
                    if sub and sub not in ("Normal", "Holofoil", "Unlimited", ""):
                        continue

                    if pid not in history:
                        history[pid] = []
                    history[pid].append((date_str, price))
                except (ValueError, TypeError):
                    continue

        except Exception as e:
            logger.warning(f"  Failed to parse {prices_file}: {e}")
            continue

    return history


def compute_stats(history: dict) -> dict:
    """
    Compute drift (mu) and volatility (sigma) per card from daily log-returns.
    Matches the Shroomy Simulator import-tcg-csv.ts logic exactly.
    """
    stats = {}
    computed = 0
    backfilled = 0

    # Group stats for backfilling
    group_stats: dict[int, dict] = {}

    GLOBAL_VOL = 0.05
    GLOBAL_DRIFT = 0.0005

    for pid, points in history.items():
        # Sort chronologically
        points.sort(key=lambda x: x[0])
        prices = [p for _, p in points if p > 0]

        entry = {
            "drift": 0.0,
            "volatility": 0.0,
            "lastPrice": prices[-1] if prices else 0.0,
            "history": [],
        }

        if len(prices) >= 2:
            returns = []
            for i in range(1, len(prices)):
                r = math.log(prices[i] / prices[i - 1])
                if not math.isnan(r):
                    returns.append(r)

            if len(returns) >= 2:
                mean_r = sum(returns) / len(returns)
                variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
                entry["drift"] = mean_r
                entry["volatility"] = math.sqrt(variance)
                computed += 1

        stats[str(pid)] = entry

    # Backfill cards with no movement using global averages
    for pid_str, entry in stats.items():
        if entry["volatility"] == 0.0 and entry["drift"] == 0.0:
            entry["volatility"] = GLOBAL_VOL
            entry["drift"] = GLOBAL_DRIFT
            backfilled += 1

    logger.info(f"Computed real stats for {computed:,} cards")
    logger.info(f"Backfilled {backfilled:,} cards with global averages")
    return stats


def merge_with_existing(new_stats: dict, existing_path: Path) -> dict:
    """
    Merge new stats with existing tcg_stats.json.
    New data overwrites old for the same product_id.
    """
    existing = {}
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text())
            logger.info(f"Loaded {len(existing):,} existing products from {existing_path.name}")
        except Exception as e:
            logger.warning(f"Could not load existing stats: {e}")

    # Merge: new overwrites old
    existing.update(new_stats)
    return existing


def main():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting {DAYS_TO_FETCH}-day TCGCSV download pipeline...")
    logger.info(f"Target categories: {TARGET_CATEGORIES}")

    successful = 0

    for i in range(1, DAYS_TO_FETCH + 1):
        date = datetime.now() - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        archive_name = f"history-{date_str}.7z"
        archive_path = TEMP_DIR / archive_name
        url = ARCHIVE_URL.format(date=date_str)

        logger.info(f"[{i}/{DAYS_TO_FETCH}] Processing {date_str}...")

        # Download if not cached
        if not archive_path.exists():
            if i > 1:
                time.sleep(POLITE_DELAY)
            if not download_file(url, archive_path):
                continue
        else:
            logger.info("  Archive cached, skipping download")

        # Extract
        if extract_categories(archive_path, HISTORY_DIR, TARGET_CATEGORIES):
            successful += 1

    # Safety check
    if successful < SAFETY_MIN_DAYS:
        logger.error(
            f"SAFETY ABORT: Only {successful} days downloaded "
            f"(minimum {SAFETY_MIN_DAYS}). Not updating stats."
        )
        sys.exit(1)

    logger.info(f"Downloaded {successful}/{DAYS_TO_FETCH} days successfully")

    # Scan and compute
    logger.info("Scanning extracted price files...")
    history = scan_price_files(HISTORY_DIR)
    logger.info(f"Found price data for {len(history):,} unique products")

    if not history:
        logger.warning("No price data found in extracted archives. Exiting.")
        sys.exit(0)

    logger.info("Computing drift and volatility...")
    new_stats = compute_stats(history)

    # Merge with existing
    merged = merge_with_existing(new_stats, OUTPUT_FILE)

    # Write output
    OUTPUT_FILE.write_text(json.dumps(merged, indent=2))
    logger.info(f"Saved {len(merged):,} products to {OUTPUT_FILE}")
    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
