#!/usr/bin/env python3
"""
vibes_ebay_tracker.py — daily eBay market tracker for Vibes TCG (Pudgy Penguins).

WHY: DYLI covers singles' floor prices, but eBay owns the Vibes SEALED secondary
market (booster boxes/cases/decks) and carries real auction prices for singles.
This gives the oracle a TWO-marketplace view (DYLI floor vs eBay market).

NOTE on sold comps: the Browse API SILENTLY IGNORES soldItemsOnly without a
Marketplace Insights entitlement (verified 2026-07-01: active vs "sold" medians
identical across 20+ products — the single-query test that looked like success
was active listings). So we store ACTIVE asks only; sold_* columns stay NULL
until/unless the Insights API is granted. Graded slab rows are active ASKS.

What it does daily (~90 API calls on the NEW enrichment key; quota headroom ~4k):
  1. SEALED: curated product list -> active median/low/high + sold median
     -> `vibes_ebay_history` (own table; vibes_price_history's PK has no source
     dimension, and a separate table keeps the DYLI accumulator untouched).
  2. SINGLES: top-N Vibes cards by DYLI cumulative volume -> same treatment.
  3. GRADED: top slab-worthy cards x PSA 10/PSA 9 SOLD comps -> the existing
     `graded_prices` table (source='ebay_vibes') — first-mover data on the
     graded Vibes market.

Type-aware filtering (lessons from the retired eBay seed): box queries must say
box, pack queries must say pack and not box; lots/bundles excluded for singles.
Read/write only the mcp .cache DB with busy_timeout (runs 4:20am, after the
pipeline + DYLI ingest). Keys from the x402 .env (EBAY_ENRICHMENT_*).
"""
import os, re, sys, sqlite3, argparse, statistics
from datetime import date, datetime

MCP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(MCP, ".cache", "market_memory.sqlite")
X402_ENV = os.path.expanduser("~/Documents/undesirables-x402-server/.env")

SEALED = [
    ("Enter the Huddle 1st Edition Booster Box",  "Vibes Enter the Huddle 1st Edition booster box sealed", ["box"], []),
    ("Enter the Huddle Booster Pack",             "Vibes Enter the Huddle booster pack sealed",            ["pack"], ["box", "case"]),
    ("Legend of the Lils Booster Box",            "Vibes Legend of the Lils booster box sealed",           ["box"], []),
    ("Birb & Pengu Booster Box",                  "Vibes Birb Pengu booster box sealed",                   ["box"], []),
    ("Birb & Pengu Booster Pack",                 "Vibes Birb Pengu booster pack sealed",                  ["pack"], ["box", "case"]),
    ("Series 3 Booster Box",                      "Vibes TCG Series 3 booster box sealed",                 ["box"], []),
    ("Vibes Duel Deck",                           "Vibes Duel Deck Pudgy Penguins sealed",                 ["deck"], ["box"]),
    ("Enter the Huddle Booster Box CASE",         "Vibes Enter the Huddle booster box case sealed",        ["case"], []),
]
_LOT = re.compile(r"\b(lot|bundle|x\s?[2-9]|[2-9]\s?x|\(\s?[2-9]\s?\)|playset|complete set)\b", re.I)
TOP_SINGLES = 20          # by DYLI cumulative total_orders
GRADED_TOP = 15           # slab queries: top cards x PSA 10 / PSA 9
EXPIRE_DAYS = 7


from vibes_dyli_ingest import variant_of
import vibes_dyli_ingest as variant_mod   # shared variant parser (name-based)
VARIANT_WORDS = ["foil", "holo", "arctic", "sketch", "diamond"]


def load_ebay():
    for line in open(X402_ENV):
        m = re.match(r"^(EBAY_[A-Z_]+)=(.*)$", line.strip())
        if m:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    # NEW enrichment key — the old key carries the graded pipeline load
    os.environ["EBAY_APP_ID"] = os.environ.get("EBAY_ENRICHMENT_APP_ID", "")
    os.environ["EBAY_CLIENT_SECRET"] = os.environ.get("EBAY_ENRICHMENT_CLIENT_SECRET", "")
    sys.path.insert(0, MCP)
    import ebay_oracle
    ebay_oracle.EBAY_APP_ID = os.environ["EBAY_APP_ID"]
    ebay_oracle.EBAY_CLIENT_SECRET = os.environ["EBAY_CLIENT_SECRET"]
    return ebay_oracle


def stats_of(rows, require=(), exclude=(), single_unit=False):
    prices = []
    for r in rows or []:
        t = (r.get("title") or "").lower()
        p = r.get("price")
        if not p or "vibe" not in t:
            continue
        if any(x not in t for x in require) or any(x in t for x in exclude):
            continue
        if single_unit and _LOT.search(t):
            continue
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            continue
    if not prices:
        return None
    prices.sort()
    return {"median": round(statistics.median(prices), 2),
            "low": round(prices[0], 2), "high": round(prices[-1], 2), "n": len(prices)}


def search(ebay, q, sold=False):
    os.environ["EBAY_FILTERS"] = "soldItemsOnly" if sold else ""
    return ebay.search_ebay_listings(q, limit=30) or []


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS vibes_ebay_history (
        product_key TEXT, name TEXT, kind TEXT,
        active_median REAL, active_low REAL, active_high REAL, active_n INTEGER,
        sold_median REAL, sold_low REAL, sold_high REAL, sold_n INTEGER,
        date TEXT, PRIMARY KEY (product_key, date))""")
    db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ebay = load_ebay()
    db = sqlite3.connect(DB, timeout=30)
    ensure_schema(db)
    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    calls = 0

    targets = [("sealed", nm, q, req, exc, False) for nm, q, req, exc in SEALED]
    # top singles by DYLI cumulative volume (proven demand -> worth eBay calls)
    single_pids = {}
    for pid, nm in db.execute(
            "SELECT product_id, name FROM vibes_price_history WHERE source='dyli' "
            "AND date=(SELECT MAX(date) FROM vibes_price_history WHERE source='dyli') "
            "AND total_orders > 0 AND name NOT LIKE '%Booster%' AND name NOT LIKE '%Box%' "
            "AND name NOT LIKE '%Deck%' AND name NOT LIKE '%Case%' AND name NOT LIKE '%Bundle%' "
            "ORDER BY total_orders DESC LIMIT ?", (TOP_SINGLES,)):
        single_pids[nm] = pid
        var = variant_of(nm)
        if var == "Common":
            # keep foil/sketch asks OUT of common medians
            targets.append(("single", nm, f"{nm} Vibes TCG", [], ["box", "case", "deck"] + VARIANT_WORDS, True))
        else:
            token = var.split()[0].lower()          # 'arctic', 'sketch', 'foil', 'diamond'
            targets.append(("single", nm, f"{nm} Vibes TCG", [token], ["box", "case", "deck"], True))

    rows_out = []
    for kind, nm, q, req, exc, single in targets:
        act = stats_of(search(ebay, q, sold=False), req, exc, single); calls += 1
        sld = None                      # Browse API has no real sold data (see docstring)
        if not act:
            continue
        key = re.sub(r"[^a-z0-9]+", "-", nm.lower()).strip("-")
        rows_out.append((key, nm, kind,
                         *(act and (act["median"], act["low"], act["high"], act["n"]) or (None,)*4),
                         *(sld and (sld["median"], sld["low"], sld["high"], sld["n"]) or (None,)*4),
                         today))
        am = act and f"${act['median']}(n{act['n']})" or "—"
        sm = sld and f"${sld['median']}(n{sld['n']})" or "—"
        print(f"  {kind:<7} {nm[:44]:<44} active {am:<14} sold {sm}")

    # graded slabs: top singles x PSA 10 / PSA 9, SOLD comps into graded_prices
    graded_rows = []
    tops = [t[1] for t in targets if t[0] == "single"][:GRADED_TOP]
    for nm in tops:
        var = variant_of(nm)
        v_req = [] if var == "Common" else [var.split()[0].lower()]
        v_exc = VARIANT_WORDS if var == "Common" else []
        for grade in ("PSA 10", "PSA 9"):
            sld = stats_of(search(ebay, f"{nm} Vibes {grade}", sold=False), [grade.split()[1]] + v_req, v_exc, True); calls += 1
            if sld:
                graded_rows.append((single_pids.get(nm, 0), nm, "Vibes TCG", grade.split()[1], "PSA",
                                    sld["median"], sld["low"], sld["high"], sld["n"], None,
                                    f"{nm} Vibes {grade}", "ebay_vibes", now,
                                    f"{today}T00:00:00+{EXPIRE_DAYS}d"))
                print(f"  graded  {nm[:38]:<38} {grade}: ask ${sld['median']} (n{sld['n']})")

    if a.dry_run:
        print(f"[dry-run] {len(rows_out)} market rows, {len(graded_rows)} graded rows, {calls} API calls — no writes")
        return
    db.executemany("INSERT OR REPLACE INTO vibes_ebay_history (product_key, name, kind, active_median, active_low, active_high, active_n, sold_median, sold_low, sold_high, sold_n, date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows_out)
    # populate the v4 cross-market-join columns for the rows just written
    for _k, _nm, *_ in rows_out:
        db.execute("UPDATE vibes_ebay_history SET base_key=?, variant=? WHERE product_key=? AND date=?",
                   (variant_mod.base_key(_nm), variant_of(_nm), _k, today))
    db.commit()          # market rows land even if the graded section fails
    if graded_rows:
        db.executemany("INSERT OR REPLACE INTO graded_prices (product_id, card_name, game_name, grade, grading_company, "
                       "median_price, low_price, high_price, num_listings, raw_market_price, ebay_search_query, "
                       "source, fetched_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", graded_rows)
    db.commit()
    print(f"✓ {now}: {len(rows_out)} market rows + {len(graded_rows)} graded rows | {calls} eBay calls (new key)")
    db.close()


if __name__ == "__main__":
    main()
