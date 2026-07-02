#!/usr/bin/env python3
"""
vibes_dyli_sales_poller.py — 15-minute poller for DYLI's live activity feed.

WHY: the daily ingest captures floor/last_sale/total_orders per card, but DYLI's
activity feed (https://www.dyli.io/api/explore/activity) is a rolling ~120-event
window with no pagination or history API — individual sales vanish within hours.
Polling every 15 min captures each PURCHASE/FLIP/TRADEIN as it happens: exact
price, timestamp, product, grade — intraday sales velocity the daily snapshot
can't see.

Design:
  - Writes to a SEPARATE append-only DB (.cache/dyli_sales.sqlite) so frequent
    writes never contend with the 3am pipeline's long exclusive lock on
    market_memory.sqlite.
  - Stores ALL sale-type events (Pokemon slabs etc. trade on DYLI too — free
    signal), flagged is_vibes by matching product_name against our Vibes catalog
    (from vibes_price_history) + set-name substrings as fallback.
  - Dedupe: rolling windows overlap between polls -> INSERT OR IGNORE on a
    content-hash uid (event id when present, else hash of type|date|name|price).
  - Excludes noise: 'spins' (gacha), 'new_users', and $1 "Fair Drop Entry"
    raffle tickets are counted but not treated as sales.

Cron: */15 * * * * with the x402 venv python (system python3 is TCC-blocked).
Stdlib only. One HTTP call per run (~96/day, trivially under DYLI's rate limit).
"""
import os, json, sqlite3, hashlib, urllib.request
from datetime import datetime, timezone

MCP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALES_DB = os.path.join(MCP, ".cache", "dyli_sales.sqlite")
MARKET_DB = os.path.join(MCP, ".cache", "market_memory.sqlite")
FEED = "https://www.dyli.io/api/explore/activity"
PULLS = "https://www.dyli.io/api/products/pulls/recent"
UA = "Mozilla/5.0 (compatible; UndesirablesOracle/1.0)"
SALE_TYPES = {"purchases", "flips", "tradeins"}
VIBES_SETS = ("enter the huddle", "legend of the lils", "birb & pengu", "birb and pengu")


def vibes_names():
    """Known Vibes product names (lowercased) from the daily ingest's accumulator."""
    try:
        c = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
        names = {r[0].lower() for r in c.execute(
            "SELECT DISTINCT name FROM vibes_price_history WHERE source='dyli'")}
        c.close()
        return names
    except Exception:
        return set()          # market DB busy (3am import) — fall back to set-substring match


def is_vibes(product_name, catalog):
    n = (product_name or "").lower()
    return n in catalog or any(s in n for s in VIBES_SETS)


def uid(e):
    if e.get("id") not in (None, "", "order"):
        return f"id:{e['id']}"
    basis = f"{e.get('type')}|{e.get('date')}|{e.get('product_name')}|{e.get('price')}|{e.get('user_username')}"
    return "h:" + hashlib.sha1(basis.encode()).hexdigest()


def main():
    db = sqlite3.connect(SALES_DB, timeout=30)
    db.execute("""CREATE TABLE IF NOT EXISTS dyli_sales_events (
        uid TEXT PRIMARY KEY, type TEXT, event_date TEXT, price REAL,
        product_name TEXT, subcategory TEXT, grade TEXT,
        is_vibes INTEGER, is_fair_drop INTEGER, raw JSON, captured_at TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dse_date ON dyli_sales_events(event_date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dse_vibes ON dyli_sales_events(is_vibes, event_date)")

    req = urllib.request.Request(FEED, headers={"User-Agent": UA})
    events = json.load(urllib.request.urlopen(req, timeout=25))
    catalog = vibes_names()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    inserted = vibes_new = 0
    for e in events:
        if e.get("type") not in SALE_TYPES:
            continue
        name = e.get("product_name") or ""
        fair = 1 if "fair drop entry" in name.lower() else 0
        row = (uid(e), e.get("type"), e.get("date"), e.get("price"), name,
               e.get("subcategory"), e.get("grade"),
               1 if is_vibes(name, catalog) else 0, fair,
               json.dumps({k: e.get(k) for k in ("tokenSetId", "user_username", "box", "packbreak", "ebay")}),
               now)
        cur = db.execute("INSERT OR IGNORE INTO dyli_sales_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
        if cur.rowcount:
            inserted += 1
            if row[7] and not fair:
                vibes_new += 1
                print(f"  🐧 VIBES SALE: {name[:56]}  ${e.get('price')}  ({e.get('type')})")
    db.commit()

    # ── pulls feed: pack-opening events (empirical pull-rate / scarcity data).
    # Rolling ~125-event window; pulls carry a real `id` + `brand`, so dedupe is
    # exact and Vibes attribution is native. ──
    db.execute("""CREATE TABLE IF NOT EXISTS dyli_pulls (
        pull_id INTEGER PRIMARY KEY, name TEXT, tokenid TEXT, price REAL,
        brand TEXT, is_pod INTEGER, pulled_at TEXT, username TEXT, captured_at TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dp_brand ON dyli_pulls(brand, pulled_at)")
    pulls_new = vibes_pulls = 0
    try:
        preq = urllib.request.Request(PULLS, headers={"User-Agent": UA})
        pdata = json.load(urllib.request.urlopen(preq, timeout=25))
        pulls = pdata if isinstance(pdata, list) else (pdata.get("pulls") or pdata.get("data") or [])
        for p in pulls:
            if not isinstance(p.get("id"), int):
                continue
            cur = db.execute("INSERT OR IGNORE INTO dyli_pulls VALUES (?,?,?,?,?,?,?,?,?)",
                             (p["id"], p.get("name"), p.get("tokenid"), p.get("price"),
                              p.get("brand"), 1 if p.get("is_pod") else 0,
                              p.get("pulledAt"), p.get("username"), now))
            if cur.rowcount:
                pulls_new += 1
                if str(p.get("brand", "")).lower() == "vibes":
                    vibes_pulls += 1
        db.commit()
    except Exception as e:
        print(f"  [pulls] fetch failed (non-fatal): {e}")

    total = db.execute("SELECT COUNT(*) FROM dyli_sales_events").fetchone()[0]
    tv = db.execute("SELECT COUNT(*) FROM dyli_sales_events WHERE is_vibes=1 AND is_fair_drop=0").fetchone()[0]
    tp = db.execute("SELECT COUNT(*) FROM dyli_pulls WHERE LOWER(brand)='vibes'").fetchone()[0]
    print(f"[{now}] feed={len(events)} ev | new sales={inserted} (vibes {vibes_new}) | new pulls={pulls_new} (vibes {vibes_pulls}) | totals: sales {total} (vibes {tv}), vibes pulls {tp}")
    db.close()


if __name__ == "__main__":
    main()
