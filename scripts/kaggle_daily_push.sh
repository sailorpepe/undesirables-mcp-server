#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# TCG Daily Kaggle Push — Automated Export + Upload
# 
# Exports fresh data from market_memory.sqlite and pushes to
# Kaggle dataset sailorpepe/tcg-price-history.
#
# Runs daily at 3am via crontab, after the GitLab CI pipeline
# finishes collecting TCGCSV data.
#
# Usage:
#   ./kaggle_daily_push.sh          # Full export + push
#   ./kaggle_daily_push.sh --dry    # Export only, no push
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
KAGGLE_DIR="$PROJECT_DIR/kaggle_dataset"
LOG_PREFIX="[Kaggle Push $(date '+%Y-%m-%d %H:%M')]"

log() { echo "$LOG_PREFIX $1"; }

log "Starting daily export..."

# Step 1: Export from SQLite using kaggle_export.py
python3 "$SCRIPT_DIR/kaggle_export.py" --output "$KAGGLE_DIR"
RESULT=$?

if [ $RESULT -ne 0 ]; then
    log "❌ Export failed (exit $RESULT)"
    exit 1
fi

# Step 2: Verify files exist and have content
for f in tcg_market_data.csv tcg_price_history.csv tcg_game_stats.csv dataset-metadata.json; do
    if [ ! -s "$KAGGLE_DIR/$f" ]; then
        log "❌ Missing or empty: $f"
        exit 1
    fi
done

MARKET_ROWS=$(wc -l < "$KAGGLE_DIR/tcg_market_data.csv" | tr -d ' ')
HISTORY_ROWS=$(wc -l < "$KAGGLE_DIR/tcg_price_history.csv" | tr -d ' ')
log "✅ Export verified: $MARKET_ROWS market rows, $HISTORY_ROWS history rows"

# Step 3: Push to Kaggle (unless --dry)
if [ "${1:-}" = "--dry" ]; then
    log "🏖️  Dry run — skipping Kaggle push"
    exit 0
fi

if ! command -v kaggle &>/dev/null; then
    log "❌ kaggle CLI not found. Install with: pip3 install kaggle"
    exit 1
fi

DATE_MSG="Daily update $(date '+%Y-%m-%d'): ${MARKET_ROWS} products, ${HISTORY_ROWS} price rows"
log "Pushing to Kaggle: $DATE_MSG"

kaggle datasets version -p "$KAGGLE_DIR" -m "$DATE_MSG" --dir-mode zip 2>&1
PUSH_RESULT=$?

if [ $PUSH_RESULT -eq 0 ]; then
    log "✅ Kaggle push complete"
else
    log "❌ Kaggle push failed (exit $PUSH_RESULT)"
    exit 1
fi

log "Done."
