#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# TCG Oracle → Kaggle Daily Auto-Update
# Runs on the Mac Mini via crontab
#
# Install:
#   chmod +x ~/Documents/undesirables-mcp-server/scripts/kaggle_daily_push.sh
#   crontab -e
#   Add: 0 3 * * * ~/Documents/undesirables-mcp-server/scripts/kaggle_daily_push.sh >> ~/logs/kaggle_push.log 2>&1
#
# This runs at 3am daily (after the GitLab CI TCGCSV pipeline finishes)
# ─────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DB_PATH="$PROJECT_DIR/.cache/market_memory.sqlite"
KAGGLE_DIR="$PROJECT_DIR/kaggle_dataset"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M')]"

# Ensure dirs exist
mkdir -p "$KAGGLE_DIR" ~/logs

echo "$LOG_PREFIX Starting Kaggle daily push..."

# Check DB exists
if [ ! -f "$DB_PATH" ]; then
    echo "$LOG_PREFIX ERROR: DB not found at $DB_PATH"
    exit 1
fi

# Export CSVs from SQLite
python3 -c "
import sqlite3, csv, os
from datetime import datetime

db = '$DB_PATH'
out_dir = '$KAGGLE_DIR'
conn = sqlite3.connect(db)
cur = conn.cursor()

# ── Export 1: Full market data (ALL cards + latest prices + stats) ──
out1 = os.path.join(out_dir, 'tcg_market_data.csv')
cur.execute('''
    SELECT c.product_id, c.name, c.clean_name, c.category_id,
           p.market_price, p.low_price, p.mid_price, p.high_price, p.date,
           s.drift, s.volatility
    FROM cards c
    LEFT JOIN price_history p ON c.product_id = p.product_id
      AND p.date = (SELECT MAX(date) FROM price_history)
    LEFT JOIN shroomy_stats s ON c.product_id = s.product_id
    ORDER BY COALESCE(p.market_price, 0) DESC
''')
rows = cur.fetchall()
with open(out1, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['product_id','name','clean_name','category_id',
                'market_price','low_price','mid_price','high_price',
                'price_date','drift','volatility'])
    w.writerows(rows)
print(f'Market data: {len(rows):,} rows')

# ── Export 2: Full price history ──
out2 = os.path.join(out_dir, 'tcg_price_history.csv')
cur.execute('''
    SELECT p.product_id, c.name, c.category_id,
           p.date, p.market_price, p.low_price, p.mid_price, p.high_price
    FROM price_history p
    JOIN cards c ON p.product_id = c.product_id
    WHERE p.market_price > 0
    ORDER BY p.product_id, p.date
''')
rows2 = cur.fetchall()
with open(out2, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['product_id','name','category_id','date',
                'market_price','low_price','mid_price','high_price'])
    w.writerows(rows2)
print(f'Price history: {len(rows2):,} rows')

# ── Export 3: Game stats ──
GAMES = {1:'Magic: The Gathering',2:'Yu-Gi-Oh!',3:'Pokemon',62:'Flesh and Blood',
         63:'Digimon',68:'One Piece',71:'Disney Lorcana',79:'Star Wars Unlimited',
         80:'Dragon Ball',81:'Union Arena',85:'Pokemon Japan',86:'Gundam',89:'LoL Riftbound'}

out3 = os.path.join(out_dir, 'tcg_game_stats.csv')
cur.execute('''
    SELECT c.category_id, COUNT(*) as total,
           COUNT(CASE WHEN p.market_price > 0 THEN 1 END) as with_pricing,
           ROUND(AVG(CASE WHEN p.market_price > 0 THEN p.market_price END), 2) as avg_price,
           MAX(p.date) as latest_date
    FROM cards c
    LEFT JOIN price_history p ON c.product_id = p.product_id
      AND p.date = (SELECT MAX(date) FROM price_history)
    GROUP BY c.category_id
    ORDER BY total DESC
''')
stats = cur.fetchall()
with open(out3, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['category_id','game','total_products','with_pricing','avg_market_price','snapshot_date'])
    for r in stats:
        w.writerow([r[0], GAMES.get(r[0], f'Category {r[0]}'), r[1], r[2], r[3], r[4]])
print(f'Game stats: {len(stats)} games')

conn.close()
print('Export complete.')
"

echo "$LOG_PREFIX CSVs exported. Starting Kaggle upload..."

# Create dataset-metadata.json if it doesn't exist
if [ ! -f "$KAGGLE_DIR/dataset-metadata.json" ]; then
    cat > "$KAGGLE_DIR/dataset-metadata.json" << 'EOF'
{
  "id": "sailorpepe/tcg-market-intelligence",
  "title": "TCG Market Intelligence — 427K+ Products + Daily Price History",
  "subtitle": "Daily prices, drift, volatility across 13 card games",
  "description": "Real market data for 427K+ trading card game products. Updated daily.",
  "keywords": ["finance"],
  "licenses": [{"name": "CC-BY-SA-4.0"}]
}
EOF
fi

# Push to Kaggle
kaggle datasets version \
    -p "$KAGGLE_DIR" \
    -m "Auto-update $(date '+%Y-%m-%d')" \
    --quiet

echo "$LOG_PREFIX Kaggle push complete!"
