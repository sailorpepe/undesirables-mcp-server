#!/usr/bin/env python3
"""
TCG Kaggle Dataset Exporter — Daily automation script.

Exports all cards, price history, and game stats from market_memory.sqlite
to CSV files for Kaggle dataset publishing.

Run after the daily TCGCSV pipeline completes.
Can be triggered by cron or GitLab CI.

Usage:
  python3 scripts/kaggle_export.py                    # Export to default output dir
  python3 scripts/kaggle_export.py --output ~/Desktop  # Export to custom dir
  python3 scripts/kaggle_export.py --push              # Export + push to Kaggle
"""

import os
import sys
import csv
import json
import sqlite3
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

WORK_DIR = Path(os.environ.get("CI_PROJECT_DIR", Path(__file__).parent.parent))
DB_PATH = WORK_DIR / ".cache" / "market_memory.sqlite"
DEFAULT_OUTPUT = WORK_DIR / "kaggle_dataset"

# category_id → game name mapping
GAMES = {
    1: "Magic: The Gathering", 2: "Yu-Gi-Oh!", 3: "Pokemon",
    62: "Flesh and Blood", 63: "Digimon", 68: "One Piece Card Game",
    71: "Disney Lorcana", 79: "Star Wars Unlimited",
    80: "Dragon Ball Super", 81: "Union Arena",
    85: "Pokemon Japan", 86: "Gundam Card Game", 89: "LoL Riftbound",
}


def export_market_data(conn, output_dir: Path) -> int:
    """Export ALL cards with latest prices and volatility stats."""
    cur = conn.cursor()
    out = output_dir / "tcg_market_data.csv"

    cur.execute("""
        SELECT c.product_id, c.name, c.clean_name, c.category_id,
               p.market_price, p.low_price, p.mid_price, p.high_price, p.date,
               s.drift, s.volatility
        FROM cards c
        LEFT JOIN price_history p ON c.product_id = p.product_id
          AND p.date = (SELECT MAX(date) FROM price_history)
        LEFT JOIN shroomy_stats s ON c.product_id = s.product_id
        ORDER BY COALESCE(p.market_price, 0) DESC
    """)
    rows = cur.fetchall()

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "name", "clean_name", "category_id",
                     "market_price", "low_price", "mid_price", "high_price",
                     "price_date", "drift", "volatility"])
        w.writerows(rows)

    priced = sum(1 for r in rows if r[4] and r[4] > 0)
    print(f"  tcg_market_data.csv: {len(rows):,} products ({priced:,} priced)")
    return len(rows)


def export_price_history(conn, output_dir: Path) -> int:
    """Export full daily price time series."""
    cur = conn.cursor()
    out = output_dir / "tcg_price_history.csv"

    cur.execute("""
        SELECT p.product_id, c.name, c.category_id,
               p.date, p.market_price, p.low_price, p.mid_price, p.high_price
        FROM price_history p
        JOIN cards c ON p.product_id = c.product_id
        WHERE p.market_price > 0
        ORDER BY p.product_id, p.date
    """)
    rows = cur.fetchall()

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "name", "category_id", "date",
                     "market_price", "low_price", "mid_price", "high_price"])
        w.writerows(rows)

    print(f"  tcg_price_history.csv: {len(rows):,} price rows")
    return len(rows)


def export_game_stats(conn, output_dir: Path) -> int:
    """Export per-game summary statistics."""
    cur = conn.cursor()
    out = output_dir / "tcg_game_stats.csv"

    cur.execute("""
        SELECT c.category_id, COUNT(*) as total,
               COUNT(CASE WHEN p.market_price > 0 THEN 1 END) as with_pricing,
               ROUND(AVG(CASE WHEN p.market_price > 0 THEN p.market_price END), 2) as avg_price,
               MAX(p.date) as latest_date
        FROM cards c
        LEFT JOIN price_history p ON c.product_id = p.product_id
          AND p.date = (SELECT MAX(date) FROM price_history)
        GROUP BY c.category_id
        ORDER BY total DESC
    """)
    stats = cur.fetchall()

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category_id", "game", "total_products", "with_pricing",
                     "avg_market_price", "snapshot_date"])
        for r in stats:
            w.writerow([r[0], GAMES.get(r[0], f"Category {r[0]}"),
                        r[1], r[2], r[3], r[4]])

    print(f"  tcg_game_stats.csv: {len(stats)} games")
    return len(stats)


def write_metadata(output_dir: Path, total_products: int, total_history: int):
    """Write/update Kaggle dataset-metadata.json."""
    meta = {
        "title": "TCG Market Intelligence 370K+ Products",
        "id": "sailorpepe/tcg-market-intelligence",
        "licenses": [{"name": "CC0-1.0"}],
        "description": (
            f"Daily TCG market prices for {total_products:,} products across 13 games "
            f"including Pokemon, Magic: The Gathering, Yu-Gi-Oh!, Star Wars Unlimited, "
            f"and more. Contains {total_history:,} daily price observations with "
            f"market/low/mid/high prices, plus drift and volatility statistics. "
            f"Updated daily from TCGCSV archives."
        ),
        "keywords": [
            "tcg", "trading-cards", "pokemon", "magic-the-gathering",
            "yu-gi-oh", "market-prices", "time-series", "finance"
        ],
        "resources": [
            {
                "path": "tcg_market_data.csv",
                "description": f"All {total_products:,} products with latest prices and volatility stats"
            },
            {
                "path": "tcg_price_history.csv",
                "description": f"Daily price time series ({total_history:,} rows)"
            },
            {
                "path": "tcg_game_stats.csv",
                "description": "Per-game summary statistics"
            },
        ],
    }

    with open(output_dir / "dataset-metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  dataset-metadata.json: updated")


def push_to_kaggle(output_dir: Path):
    """Push dataset to Kaggle using the CLI."""
    try:
        result = subprocess.run(
            ["kaggle", "datasets", "version", "-p", str(output_dir),
             "-m", f"Daily update {datetime.now().strftime('%Y-%m-%d')}",
             "--dir-mode", "zip"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            print(f"  ✅ Kaggle push succeeded")
            print(f"  {result.stdout.strip()}")
        else:
            print(f"  ❌ Kaggle push failed: {result.stderr.strip()}")
    except FileNotFoundError:
        print("  ❌ kaggle CLI not found. Install with: pip3 install kaggle")
    except subprocess.TimeoutExpired:
        print("  ❌ Kaggle push timed out (>5 min)")


def main():
    parser = argparse.ArgumentParser(description="Export TCG data for Kaggle")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output directory for CSVs")
    parser.add_argument("--push", action="store_true",
                        help="Push to Kaggle after export")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        sys.exit(1)

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"[Kaggle Export] Database: {DB_PATH}")
    print(f"[Kaggle Export] Output: {args.output}")
    conn = sqlite3.connect(str(DB_PATH))

    # Date range
    date_range = conn.execute("SELECT MIN(date), MAX(date) FROM price_history").fetchone()
    days = conn.execute("SELECT COUNT(DISTINCT date) FROM price_history").fetchone()[0]
    print(f"[Kaggle Export] Date range: {date_range[0]} → {date_range[1]} ({days} days)")
    print()

    total_products = export_market_data(conn, args.output)
    total_history = export_price_history(conn, args.output)
    export_game_stats(conn, args.output)
    write_metadata(args.output, total_products, total_history)

    conn.close()

    # File sizes
    print()
    for f in args.output.glob("*.csv"):
        sz = f.stat().st_size / 1024 / 1024
        print(f"  {f.name}: {sz:.1f} MB")

    if args.push:
        print()
        push_to_kaggle(args.output)

    print(f"\n✅ Export complete")


if __name__ == "__main__":
    main()
