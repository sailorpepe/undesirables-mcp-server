#!/bin/bash
# ═══════════════════════════════════════════════════
# TCG Daily Pipeline — Fetch + Import + Kaggle Push
# Runs daily at 3am via crontab
# ═══════════════════════════════════════════════════
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"
export KAGGLE_API_TOKEN="KGAT_dff2b369c75b7b42b1dd45b2dac06d5a"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG="$HOME/logs/daily_pipeline.log"

mkdir -p "$HOME/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M')] $1" >> "$LOG"; }

log "=== Starting daily pipeline ==="

cd "$PROJECT_DIR"

# Step 1: Download yesterday's prices
log "Step 1: Downloading prices..."
python3 scripts/tcg_cron.py >> "$LOG" 2>&1 || { log "❌ tcg_cron.py failed"; exit 1; }

# Step 2: Import to SQLite
log "Step 2: Importing to SQLite..."
python3 scripts/import_to_sqlite.py >> "$LOG" 2>&1 || { log "❌ import_to_sqlite.py failed"; exit 1; }

# Step 3: Export and push to Kaggle
log "Step 3: Pushing to Kaggle..."
python3 scripts/kaggle_export.py --output /tmp/kaggle_daily --push >> "$LOG" 2>&1 || log "⚠️ Kaggle push failed (non-fatal)"

log "=== Pipeline complete ==="
