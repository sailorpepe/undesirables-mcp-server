#!/usr/bin/env python3
"""
vibes_ebay_ingest.py — INTERIM indexer for Vibes TCG (Pudgy Penguins / Orange Cap
Games) into the oracle, sourced from eBay (Vibes is NOT in TCGplayer/TCGCSV yet, so
the normal catalog pipeline can't see it — when TCGCSV adds a Vibes category the
daily pipeline auto-ingests it and this becomes redundant).

Design (respects the existing schema + the 3am pipeline which does DELETE FROM
price_history):
  - Vibes cards -> `cards` via INSERT OR IGNORE (additive; survives the nightly
    pipeline) + synced into the external-content `cards_fts` index so /api/v1/search
    finds them. Synthetic product_ids in the 9_500_000+ range (no TCGplayer collision).
  - Price history -> a PERSISTENT `vibes_price_history` table the pipeline never
    touches (accumulates real daily history), then MIRRORED into the main
    `price_history` so /api/v1/search + /api/v1/market show current prices. The
    mirror is re-applied each run because the 3am import wipes price_history.

Run order matters: schedule AFTER the 3am TCGCSV import and BEFORE the 4:30 forecast
cron (≈4:00am) so the mirror is present for both serving and the ledger.

Read-only on TCGCSV; numpy/stdlib only; eBay keys from the x402 .env. Idempotent.
"""
import os, re, sys, sqlite3, argparse, statistics
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.dirname(HERE)
DEF_DB = os.path.join(MCP, ".cache", "market_memory.sqlite")
X402_ENV = os.path.expanduser("~/Documents/undesirables-x402-server/.env")

VIBES_CATEGORY_ID = 9001          # synthetic; TCGCSV categories are 1..90
VIBES_PID_BASE = 9_500_000        # synthetic product_id base (real TCGplayer max ~701K)

# Curated, high-signal Vibes products. (idx -> stable synthetic product_id)
VIBES_PRODUCTS = [
    ("Enter the Huddle 1st Edition Booster Box", "Vibes Enter the Huddle 1st Edition Booster Box sealed", "Sealed"),
    ("Enter the Huddle Booster Pack",            "Vibes Enter the Huddle booster pack sealed",            "Sealed"),
    ("Legend of the Lils Booster Box",           "Vibes Legend of the Lils booster box sealed",           "Sealed"),
    ("Legend of the Lils Booster Pack",          "Vibes Legend of the Lils booster pack sealed",          "Sealed"),
    ("Series 3 Booster Box",                     "Vibes Series 3 booster box sealed Pudgy Penguins",      "Sealed"),
    ("Series 3 Booster Pack",                    "Vibes Series 3 booster pack sealed Pudgy Penguins",     "Sealed"),
    ("Vibes Duel Deck",                          "Vibes Duel Deck Pudgy Penguins sealed",                 "Sealed"),
    ("Abstract Penguin",                         "Vibes TCG Abstract Penguin card",                       "Normal"),
    ("Pengu Promo",                              "Vibes TCG Pengu promo card",                            "Promo"),
]

_LOT = re.compile(r"\b(lot|bundle|x\s?[2-9]|[2-9]\s?x|\(\s?[2-9]\s?\)|playset|complete set)\b", re.I)


def load_ebay():
    for line in open(X402_ENV):
        m = re.match(r"^(EBAY_[A-Z_]+)=(.*)$", line.strip())
        if m:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    os.environ.setdefault("EBAY_APP_ID", os.environ.get("EBAY_ENRICHMENT_APP_ID", ""))
    os.environ.setdefault("EBAY_CLIENT_SECRET", os.environ.get("EBAY_ENRICHMENT_CLIENT_SECRET", ""))
    sys.path.insert(0, MCP)
    import ebay_oracle
    ebay_oracle.EBAY_APP_ID = os.environ["EBAY_APP_ID"]
    ebay_oracle.EBAY_CLIENT_SECRET = os.environ["EBAY_CLIENT_SECRET"]
    return ebay_oracle


def price_product(ebay, name, query, single_unit):
    """Median/low/high of on-topic active Vibes listings for one product. Type-aware:
    eBay keyword search conflates box/pack, so require the product's own form-factor
    token in the title (and exclude the wrong one) to keep box≠pack≠deck."""
    nl = name.lower()
    require = []; exclude = []
    if "box" in nl:
        require.append("box")
    if "pack" in nl:
        require.append("pack"); exclude.append("box")
    if "deck" in nl:
        require.append("deck"); exclude.append("box")
    rows = ebay.search_ebay_listings(query, limit=40) or []
    prices = []
    for r in rows:
        t = (r.get("title") or "").lower()
        p = r.get("price")
        if not p or "vibe" not in t:
            continue
        if any(req not in t for req in require) or any(ex in t for ex in exclude):
            continue
        if single_unit and _LOT.search(t):    # exclude multi-packs/lots for single units
            continue
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            continue
    if not prices:
        return None
    prices.sort()
    return {"market": round(statistics.median(prices), 2),
            "low": round(prices[0], 2), "high": round(prices[-1], 2), "n": len(prices)}


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS vibes_price_history (
        product_id INTEGER, name TEXT, sub_type TEXT, market_price REAL,
        low_price REAL, high_price REAL, num_listings INTEGER, date TEXT, source TEXT,
        PRIMARY KEY (product_id, date))""")
    db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEF_DB)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ebay = load_ebay()
    db = sqlite3.connect(a.db)
    ensure_schema(db)
    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")

    priced = []
    for i, (name, query, kind) in enumerate(VIBES_PRODUCTS):
        pid = VIBES_PID_BASE + i
        pr = price_product(ebay, name, query, single_unit=(kind != "Sealed" or "Pack" in name))
        if not pr:
            print(f"  [skip] {name}: no on-topic listings")
            continue
        priced.append((pid, name, kind, pr))
        print(f"  {name:<42} ${pr['market']:>8.2f}  (n={pr['n']}, {pr['low']}–{pr['high']})")

    if a.dry_run:
        print(f"[dry-run] {len(priced)} products priced; no DB writes.")
        return
    if not priced:
        print("[!] nothing priced — leaving DB untouched."); return

    # 1) cards (additive) + FTS sync
    for pid, name, kind, pr in priced:
        full = f"Vibes - {name}"
        clean = re.sub(r"[^A-Za-z0-9 ]", "", full).strip()
        cur = db.execute("INSERT OR IGNORE INTO cards (product_id, name, clean_name, category_id, rarity) "
                         "VALUES (?,?,?,?,?)", (pid, full, clean, VIBES_CATEGORY_ID, kind))
        if cur.rowcount:        # new row -> add to external-content FTS index
            rid = db.execute("SELECT rowid FROM cards WHERE product_id=?", (pid,)).fetchone()[0]
            db.execute("INSERT INTO cards_fts(rowid, name, clean_name) VALUES (?,?,?)", (rid, full, clean))

    # 2) persistent accumulator (survives the nightly DELETE FROM price_history)
    db.executemany("INSERT OR REPLACE INTO vibes_price_history "
                   "(product_id, name, sub_type, market_price, low_price, high_price, num_listings, date, source) "
                   "VALUES (?,?,?,?,?,?,?,?, 'ebay')",
                   [(pid, name, kind, pr["market"], pr["low"], pr["high"], pr["n"], today) for pid, name, kind, pr in priced])

    # 3) mirror the FULL accumulated Vibes history into the main price_history so
    #    /api/v1/search + /api/v1/market show Vibes (re-applied each run after the wipe)
    db.execute(f"DELETE FROM price_history WHERE product_id >= {VIBES_PID_BASE}")
    db.executemany("INSERT INTO price_history (product_id, market_price, low_price, mid_price, high_price, date, sub_type) "
                   "VALUES (?,?,?,?,?,?, 'Normal')",
                   [(r[0], r[3], r[4], r[3], r[5], r[7]) for r in
                    db.execute("SELECT product_id, name, sub_type, market_price, low_price, high_price, num_listings, date "
                               "FROM vibes_price_history").fetchall()])
    db.commit()
    n_hist = db.execute("SELECT COUNT(*) FROM vibes_price_history").fetchone()[0]
    print(f"✓ {now}: {len(priced)} Vibes products priced | vibes_price_history rows {n_hist} | "
          f"mirrored into price_history. category_id={VIBES_CATEGORY_ID}")
    db.close()


if __name__ == "__main__":
    main()
