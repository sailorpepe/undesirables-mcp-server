#!/usr/bin/env python3
"""
vibes_dyli_ingest.py — PRIMARY Vibes TCG (Pudgy Penguins) indexer, sourced from
DYLI's open marketplace API (https://www.dyli.io/api/explore). DYLI carries the full
Vibes catalog as structured card-level data (name, set, card id, rarity, floor /
last-sale / supply), so this supersedes the eBay seed (vibes_ebay_ingest.py).

Becomes redundant when TCGplayer/TCGCSV adds a Vibes category (the daily pipeline
auto-ingests all categories).

Schema discipline (the 3am import does DELETE FROM price_history):
  - cards via INSERT OR IGNORE (additive; synthetic product_id = 9_600_000 + dyli_id,
    category 9001) + synced into external-content cards_fts so /api/v1/search finds them.
  - Real daily snapshots accumulate in the persistent `vibes_price_history` table.
  - Latest snapshot is MIRRORED into the main price_history *dated to the TCGCSV max
    date* — NOT today — so MAX(date) never shifts (shifting it hides prices for every
    normal card in search/market). Re-applied each run after the nightly wipe.

Read-only on TCGCSV otherwise; stdlib only; no auth (DYLI /api/explore is open).
"""
import os
import re, re, sys, json, time, sqlite3, argparse, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.dirname(HERE)
DEF_DB = os.path.join(MCP, ".cache", "market_memory.sqlite")
EXPLORE = "https://www.dyli.io/api/explore?page={page}&limit=50"
UA = "Mozilla/5.0 (compatible; UndesirablesOracle/1.0)"
VIBES_CATEGORY_ID = 9001
PID_BASE = 9_600_000          # dyli_id namespace (eBay seed uses 9_500_000..9_599_999)


def fetch_page(page):
    req = urllib.request.Request(EXPLORE.format(page=page), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def parse_details(s):
    d = {}
    for line in (s or "").split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            d[k.strip().lower()] = v.strip()
    return d


def collect_vibes(max_pages=80):
    out = {}
    for page in range(1, max_pages + 1):
        data = None
        for attempt in range(3):                 # retry (esp. 429) with backoff
            try:
                data = fetch_page(page); break
            except Exception as e:
                if attempt == 2:
                    print(f"  [page {page}] fetch error after retries: {e}")
                else:
                    time.sleep(6)
        if data is None:
            break
        prods = data.get("products", [])
        for p in prods:
            if str(p.get("brand", "")).lower() != "vibes":
                continue
            if str(p.get("category", "")).upper() != "TCG":
                continue
            did = p.get("id")
            if not isinstance(did, int) or did >= 100_000:     # keep the synthetic id range clean
                continue
            out[did] = p
        if not data.get("hasMore"):
            break
        time.sleep(0.9)         # stay under the ~70/window rate limit
    return out


def market_of(p):
    for k in ("lowest_price", "last_sale", "price"):
        v = p.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


VARIANT_PATTERNS = [           # order matters: most specific first
    ("Arctic Foil", r"arctic\s*foil|arctic"),
    ("Sketch",      r"\bsketch\b"),
    ("Diamond",     r"\bdiamond\b"),
    ("Foil",        r"\bfoil\b|holofoil|\bholo\b"),
    ("Graded Exclusive", r"\b(psa|sgc|cgc|bgs)\b.*exclusive|exclusive.*\b(psa|sgc|cgc|bgs)\b"),
]

def variant_of(name, tcg_subtype=None):
    """Vibes variant from the product NAME — DYLI's tcg_subtype is ~97% 'Normal'
    even for foils, but names reliably carry 'Foil', 'Arctic Foil', 'Sketch',
    'Diamond', or grader-exclusive markers. Default: Common."""
    low = (name or "").lower()
    for label, pat in VARIANT_PATTERNS:
        if re.search(pat, low):
            return label
    if tcg_subtype and tcg_subtype not in ("Normal", "None", None):
        return tcg_subtype
    return "Common"


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS vibes_price_history (
        product_id INTEGER, name TEXT, sub_type TEXT, market_price REAL,
        low_price REAL, high_price REAL, num_listings INTEGER, date TEXT, source TEXT,
        PRIMARY KEY (product_id, date))""")
    try:                                  # card art URL (Vibes uses DYLI/OCG S3, not TCGplayer CDN)
        db.execute("ALTER TABLE cards ADD COLUMN image_url TEXT")
    except Exception:
        pass
    # sales signals (DYLI has no historical-sales API, so we accrue these daily:
    # last_sale = last traded price, total_orders = cumulative sales -> day-over-day
    # delta is units sold that day, highest_bid = top bid, supply = total minted)
    for col, typ in (("last_sale", "REAL"), ("total_orders", "INTEGER"),
                     ("highest_bid", "REAL"), ("supply", "INTEGER")):
        try:
            db.execute(f"ALTER TABLE vibes_price_history ADD COLUMN {col} {typ}")
        except Exception:
            pass
    db.commit()


def image_of(p):
    return (p.get("main_image_override") or (p.get("images") or [None])[0]
            or p.get("master_image") or None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEF_DB)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    vibes = collect_vibes()
    print(f"  collected {len(vibes)} Vibes TCG products from DYLI")
    rows = []
    for did, p in vibes.items():
        mk = market_of(p)
        if mk is None:
            continue
        det = parse_details(p.get("details_override"))
        name = re.sub(r"\s+", " ", str(p.get("name", "")).strip())
        pid = PID_BASE + did
        rarity = det.get("rarity") or p.get("subcategory") or ""
        rows.append({
            "pid": pid, "name": name, "rarity": rarity,
            "sub_type": variant_of(p.get("name"), p.get("tcg_subtype")),
            "market": round(mk, 2),
            "low": round(float(p.get("lowest_price") or mk), 2),
            "high": round(float(p.get("price") or mk), 2),
            "avail": int(p.get("total_available_auto") or 0),
            "image": image_of(p),
            "last_sale": float(p["last_sale"]) if p.get("last_sale") else None,
            "orders": int(p.get("total_orders") or 0),
            "bid": float(p["highest_bid"]) if p.get("highest_bid") else None,
            "supply": int(p.get("supply") or 0),
        })
    print(f"  {len(rows)} priced; sample:", [(r['name'][:34], r['market']) for r in rows[:3]])
    if a.dry_run:
        print(f"[dry-run] {len(rows)} Vibes products; no DB writes."); return
    if not rows:
        print("[!] nothing priced — DB untouched."); return

    today = date.today().isoformat()
    db = sqlite3.connect(a.db)
    ensure_schema(db)
    tcg_max = db.execute("SELECT MAX(date) FROM price_history WHERE product_id < 9500000").fetchone()[0]

    # Observability: DYLI delists sold-out/removed products (their history tail stops
    # accruing). Log what vanished vs the previous snapshot so drops aren't silent.
    prev_date = db.execute("SELECT MAX(date) FROM vibes_price_history WHERE source='dyli' AND date < ?",
                           (today,)).fetchone()[0]
    if prev_date:
        prev = {r[0]: r[1] for r in db.execute(
            "SELECT product_id, name FROM vibes_price_history WHERE source='dyli' AND date=?", (prev_date,))}
        now_pids = {r["pid"] for r in rows}
        gone = [(p, n) for p, n in prev.items() if p not in now_pids]
        if gone:
            print(f"  [delisted] {len(gone)} card(s) vanished from DYLI since {prev_date}:")
            for p, n in gone[:10]:
                print(f"    - {n[:60]} (pid {p})")

    # 1) cards (additive) + FTS sync
    for r in rows:
        nm = r["name"]
        full = nm if nm.lower().startswith("vibes") else f"Vibes - {nm}"   # avoid "Vibes - Vibes - ..."
        clean = re.sub(r"[^A-Za-z0-9 ]", "", full).strip()
        cur = db.execute("INSERT OR IGNORE INTO cards (product_id, name, clean_name, category_id, rarity) VALUES (?,?,?,?,?)",
                         (r["pid"], full, clean, VIBES_CATEGORY_ID, r["rarity"]))
        if cur.rowcount:
            rid = db.execute("SELECT rowid FROM cards WHERE product_id=?", (r["pid"],)).fetchone()[0]
            db.execute("INSERT INTO cards_fts(rowid, name, clean_name) VALUES (?,?,?)", (rid, full, clean))
        db.execute("UPDATE cards SET image_url=? WHERE product_id=?", (r["image"], r["pid"]))

    # 2) persistent accumulator (real date; survives the nightly wipe)
    db.executemany("INSERT OR REPLACE INTO vibes_price_history "
                   "(product_id, name, sub_type, market_price, low_price, high_price, num_listings, date, source, "
                   " last_sale, total_orders, highest_bid, supply) "
                   "VALUES (?,?,?,?,?,?,?,?, 'dyli', ?,?,?,?)",
                   [(r["pid"], r["name"], r["sub_type"], r["market"], r["low"], r["high"], r["avail"], today,
                     r["last_sale"], r["orders"], r["bid"], r["supply"]) for r in rows])

    # 3) mirror latest snapshot into price_history at the TCGCSV max date (do NOT shift MAX(date))
    db.execute(f"DELETE FROM price_history WHERE product_id >= {PID_BASE}")
    db.executemany("INSERT INTO price_history (product_id, market_price, low_price, mid_price, high_price, date, sub_type) "
                   "VALUES (?,?,?,?,?,?, 'Normal')",
                   [(r["pid"], r["market"], r["low"], r["market"], r["high"], tcg_max) for r in rows])
    db.commit()
    n_cards = db.execute("SELECT COUNT(*) FROM cards WHERE category_id=9001 AND product_id>=?", (PID_BASE,)).fetchone()[0]
    n_hist = db.execute("SELECT COUNT(*) FROM vibes_price_history WHERE source='dyli'").fetchone()[0]
    print(f"✓ DYLI ingest: {len(rows)} priced | Vibes(DYLI) cards {n_cards} | accumulator rows {n_hist} | mirrored at date {tcg_max}")
    db.close()


if __name__ == "__main__":
    main()
