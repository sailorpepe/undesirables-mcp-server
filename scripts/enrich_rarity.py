#!/usr/bin/env python3
"""
enrich_rarity.py — Backfill cards.rarity from TCGCSV product extendedData.

The daily import only fetches product details for NEW products, so existing cards
have NULL rarity. This walks every category/group in the latest on-disk archive,
fetches that group's products from TCGCSV, pulls the "Rarity" extendedData field,
and UPDATEs cards.rarity. Only fills rows where rarity is empty → safe to re-run
and resumes naturally. Sealed products legitimately have no rarity (left NULL).
"""
import sqlite3, urllib.request, json, time, sys
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent.parent
DB = WORK_DIR / ".cache" / "market_memory.sqlite"
HISTORY = WORK_DIR / "tmp_history"
RATE = 0.3  # seconds between group fetches (matches the import; ~3 req/s)


def latest_date_dir():
    dirs = sorted(d for d in HISTORY.iterdir() if d.is_dir() and len(d.name) == 10)
    return dirs[-1] if dirs else None


def category_group_combos(date_dir):
    combos = set()
    for cat in date_dir.iterdir():
        if cat.is_dir() and cat.name.isdigit():
            for grp in cat.iterdir():
                if grp.is_dir() and grp.name.isdigit():
                    combos.add((int(cat.name), int(grp.name)))
    return sorted(combos)


def fetch_products(cat, grp, tries=2):
    url = f"https://tcgcsv.com/tcgplayer/{cat}/{grp}/products"
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 TCGOracle/2.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                d = json.loads(resp.read())
                return d.get("results", d if isinstance(d, list) else [])
        except Exception:
            time.sleep(1)
    return []


def rarity_of(p):
    return next((e.get("value") for e in p.get("extendedData", []) if e.get("name") == "Rarity"), None)


def main():
    conn = sqlite3.connect(str(DB))
    dd = latest_date_dir()
    if not dd:
        print("No tmp_history date dir found"); return 1
    combos = category_group_combos(dd)
    start_have = conn.execute("SELECT COUNT(*) FROM cards WHERE rarity IS NOT NULL AND rarity!=''").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    print(f"[enrich_rarity] {len(combos)} groups from {dd.name}. Cards with rarity at start: {start_have:,}/{total:,}", flush=True)

    for i, (cat, grp) in enumerate(combos, 1):
        products = fetch_products(cat, grp)
        rows = [(r, int(p["productId"])) for p in products
                if (r := rarity_of(p)) and p.get("productId")]
        if rows:
            conn.executemany(
                "UPDATE cards SET rarity=? WHERE product_id=? AND (rarity IS NULL OR rarity='')", rows)
            conn.commit()
        if i % 100 == 0 or i == len(combos):
            have = conn.execute("SELECT COUNT(*) FROM cards WHERE rarity IS NOT NULL AND rarity!=''").fetchone()[0]
            print(f"  {i}/{len(combos)} groups | cards with rarity: {have:,}", flush=True)
        time.sleep(RATE)

    have = conn.execute("SELECT COUNT(*) FROM cards WHERE rarity IS NOT NULL AND rarity!=''").fetchone()[0]
    print(f"[enrich_rarity] DONE. {have:,}/{total:,} cards now have a rarity (+{have-start_have:,}).", flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
