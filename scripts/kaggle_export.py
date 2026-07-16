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
        SELECT c.product_id, c.name, c.clean_name, c.category_id, c.rarity,
               p.sub_type, p.market_price, p.low_price, p.mid_price, p.high_price,
               p.date, s.drift, s.volatility
        FROM cards c
        LEFT JOIN price_history p ON c.product_id = p.product_id
          AND p.date = (SELECT MAX(date) FROM price_history)
        LEFT JOIN shroomy_stats s ON c.product_id = s.product_id
        ORDER BY COALESCE(p.market_price, 0) DESC
    """)
    rows = cur.fetchall()

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "name", "clean_name", "category_id", "rarity",
                     "sub_type", "market_price", "low_price", "mid_price",
                     "high_price", "price_date", "drift", "volatility"])
        w.writerows(rows)

    priced = sum(1 for r in rows if r[6] and r[6] > 0)
    print(f"  tcg_market_data.csv: {len(rows):,} products ({priced:,} priced)")
    return len(rows)


def export_price_history(conn, output_dir: Path) -> int:
    """Export full daily price time series."""
    cur = conn.cursor()
    out = output_dir / "tcg_price_history.csv"

    cur.execute("""
        SELECT p.product_id, c.name, c.category_id, p.sub_type,
               p.date, p.market_price, p.low_price, p.mid_price, p.high_price
        FROM price_history p
        JOIN cards c ON p.product_id = c.product_id
        WHERE p.market_price > 0
        ORDER BY p.product_id, p.date, p.sub_type
    """)
    rows = cur.fetchall()

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "name", "category_id", "sub_type", "date",
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


def write_metadata(output_dir: Path, total_products: int, total_history: int,
                   total_categories: int = 0, total_days: int = 0):
    """Write/update Kaggle dataset-metadata.json."""
    # Subtitle auto-updates from the real category/day counts each run.
    # NOTE: "categories" (= COUNT(DISTINCT category_id)), not "games" — TCGplayer
    # categories include supplies/accessories/miniatures, not only card games.
    # Kaggle requires the subtitle to be 20-80 characters.
    subtitle = (f"Daily prices, rarity & volatility — {total_categories} TCGplayer "
                f"categories, {total_days}-day series")[:80]
    meta = {
        "title": "TCG Market Intelligence 370K+ Products",
        "id": "sailorpepe/tcg-market-intelligence",
        "subtitle": subtitle,
        "licenses": [{"name": "CC0-1.0"}],
        "description": (
            f"Daily TCG market prices for {total_products:,} products across "
            f"{total_categories} TCGplayer categories — including Pokemon, Magic: The "
            f"Gathering, Yu-Gi-Oh!, Lorcana, One Piece, Star Wars Unlimited, and more. "
            f"Contains {total_history:,} daily price observations with "
            f"market/low/mid/high prices broken out by printing (Normal/Holofoil), "
            f"card rarity, plus drift and volatility statistics. "
            f"Updated daily from TCGCSV archives."
        ),
        # Kaggle tags must come from Kaggle's own taxonomy — free-form keywords
        # (tcg, pokemon, time-series, ...) are rejected on every push ("not
        # valid tags", seen 2026-07-16). "finance" was the only survivor of the
        # old list; the rest below are standard Kaggle category tags.
        "keywords": [
            "finance", "games", "card games", "time series analysis",
            "economics", "investing"
        ],
        "resources": [
            {
                "path": "tcg_market_data.csv",
                "description": f"All {total_products:,} products with their most recent daily price snapshot, card rarity, and drift/volatility statistics. One row per product.",
                "schema": {
                    "fields": [
                        {"name": "product_id", "description": "TCGplayer product ID. Unique, stable identifier for each product. Join key to tcg_price_history.csv.", "type": "integer"},
                        {"name": "name", "description": "Full product name as listed on TCGplayer (e.g. 'Charizard ex - 199/165').", "type": "string"},
                        {"name": "clean_name", "description": "Normalized product name with punctuation and special characters stripped (e.g. 'Charizard ex 199165'). Useful for fuzzy matching and search.", "type": "string"},
                        {"name": "category_id", "description": "TCGplayer category ID identifying the game/product line (e.g. 1 = Magic: The Gathering, 2 = Yu-Gi-Oh!, 3 = Pokemon). See tcg_game_stats.csv for the full ID-to-game mapping.", "type": "integer"},
                        {"name": "rarity", "description": "Card rarity as defined by TCGplayer, specific to each game (e.g. Pokemon: Common / Uncommon / Rare / Double Rare / Illustration Rare; Magic: Common / Uncommon / Rare / Mythic). Empty for sealed products (booster boxes, packs, decks), which have no rarity.", "type": "string"},
                        {"name": "sub_type", "description": "Printing/variant the price refers to: 'Normal', 'Holofoil', or 'Unlimited' (empty for products with a single printing). A card with multiple printings appears as multiple rows here, one per sub_type, since each prints at a different price.", "type": "string"},
                        {"name": "market_price", "description": "TCGplayer Market Price in USD on price_date — the benchmark fair-market value derived from recent sales.", "type": "number"},
                        {"name": "low_price", "description": "Lowest active listing price in USD on price_date.", "type": "number"},
                        {"name": "mid_price", "description": "Mid/median listing price in USD on price_date.", "type": "number"},
                        {"name": "high_price", "description": "Highest active listing price in USD on price_date.", "type": "number"},
                        {"name": "price_date", "description": "Date of this price snapshot (YYYY-MM-DD).", "type": "string"},
                        {"name": "drift", "description": "Annualized expected log-return (mu) estimated from the product's historical price series. Used as the drift (mu) parameter in the oracle's price-forecast models.", "type": "number"},
                        {"name": "volatility", "description": "Annualized volatility (sigma) estimated from the product's historical price series. Used as the diffusion (sigma) parameter in the oracle's price-forecast models.", "type": "number"},
                    ]
                },
            },
            {
                "path": "tcg_price_history.csv",
                "description": f"Full daily price time series ({total_history:,} rows). One row per product per day with a recorded market price.",
                "schema": {
                    "fields": [
                        {"name": "product_id", "description": "TCGplayer product ID. Join key to tcg_market_data.csv.", "type": "integer"},
                        {"name": "name", "description": "Full product name as listed on TCGplayer.", "type": "string"},
                        {"name": "category_id", "description": "TCGplayer category ID identifying the game/product line. See tcg_game_stats.csv for the ID-to-game mapping.", "type": "integer"},
                        {"name": "sub_type", "description": "Printing/variant this price refers to: 'Normal', 'Holofoil', or 'Unlimited' (empty for single-printing products). Together with product_id and date this identifies a unique price observation — a card with both Normal and Holofoil printings has two rows per date.", "type": "string"},
                        {"name": "date", "description": "Date of this price observation (YYYY-MM-DD).", "type": "string"},
                        {"name": "market_price", "description": "TCGplayer Market Price in USD on this date.", "type": "number"},
                        {"name": "low_price", "description": "Lowest active listing price in USD on this date.", "type": "number"},
                        {"name": "mid_price", "description": "Mid/median listing price in USD on this date.", "type": "number"},
                        {"name": "high_price", "description": "Highest active listing price in USD on this date.", "type": "number"},
                    ]
                },
            },
            {
                "path": "tcg_game_stats.csv",
                "description": "Per-game summary statistics. One row per game/category, providing the canonical category_id-to-game mapping.",
                "schema": {
                    "fields": [
                        {"name": "category_id", "description": "TCGplayer category ID. Foreign key referenced by category_id in the other two files.", "type": "integer"},
                        {"name": "game", "description": "Human-readable game name for this category_id (e.g. 'Pokemon', 'Magic: The Gathering').", "type": "string"},
                        {"name": "total_products", "description": "Total number of products tracked for this game.", "type": "integer"},
                        {"name": "with_pricing", "description": "Number of those products that have a market price on the latest snapshot date.", "type": "integer"},
                        {"name": "avg_market_price", "description": "Average market price in USD across priced products for this game on the latest snapshot date.", "type": "number"},
                        {"name": "snapshot_date", "description": "Latest price snapshot date used for these statistics (YYYY-MM-DD).", "type": "string"},
                    ]
                },
            },
        ],
    }

    with open(output_dir / "dataset-metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  dataset-metadata.json: updated")


def push_to_kaggle(output_dir: Path):
    """Push dataset to Kaggle using the CLI.

    Timeout is 30 min: the price_history CSV is ~1GB and the old 300s cap
    caused 21 consecutive silent timeouts (Jun 25–Jul 16, dataset went stale
    ~3 weeks before anyone noticed). Duration is logged to tune this from
    data rather than guesses."""
    import time
    t0 = time.time()
    try:
        result = subprocess.run(
            ["kaggle", "datasets", "version", "-p", str(output_dir),
             "-m", f"Daily update {datetime.now().strftime('%Y-%m-%d')}",
             "--dir-mode", "zip"],
            capture_output=True, text=True, timeout=1800,
        )
        mins = (time.time() - t0) / 60
        if result.returncode == 0:
            print(f"  ✅ Kaggle push succeeded in {mins:.1f} min")
            print(f"  {result.stdout.strip()}")
        else:
            print(f"  ❌ Kaggle push failed after {mins:.1f} min: {result.stderr.strip()}")
    except FileNotFoundError:
        print("  ❌ kaggle CLI not found. Install with: pip3 install kaggle")
    except subprocess.TimeoutExpired:
        print(f"  ❌ Kaggle push timed out (>{1800//60} min)")


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
    total_categories = export_game_stats(conn, args.output)
    write_metadata(args.output, total_products, total_history,
                   total_categories, days)

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
