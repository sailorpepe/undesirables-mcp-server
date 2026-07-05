#!/usr/bin/env python3
"""
vibes_pack_ev.py — expected value per Vibes pack, from OUR OWN pulls tape.

Combines two datasets nobody else has together:
  1. dyli_pulls (15-min poller): empirical pull events per card/variant
  2. vibes_price_history (daily, variant-tagged): current floor per pulled card

EV(set) = Σ over observed pulls[ floor(pulled card) ] / n_pulls_observed
— i.e. the average market value of an observed pull, per set.
CAVEAT: DYLI's pulls feed may over-represent notable pulls (selection bias);
treat EV as an UPPER BOUND until the tape is deep enough to compare against
known print-sheet odds. Compared against
current pack floor prices to get EV ratio ("is ripping packs +EV?").

HONEST-SAMPLE DISCIPLINE: prints n everywhere; refuses a headline number for
sets with < MIN_PULLS observed. This report gets sharper automatically as the
tape grows — rerun anytime:
  venv/bin/python scripts/vibes_pack_ev.py
"""
import os, re, sqlite3

MKT = os.path.expanduser("~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite")
SAL = os.path.expanduser("~/Documents/undesirables-mcp-server/.cache/dyli_sales.sqlite")
MIN_PULLS = 30            # below this, the EV is anecdote, not estimate

SETS = {
    "legend of the lils": "Legend of the Lils",
    "lils": "Legend of the Lils",
    "enter the huddle": "Enter the Huddle",
    "huddle": "Enter the Huddle",
    "birb": "Birb & Pengu",
    "pengu": "Birb & Pengu",
}


def set_of(name):
    low = (name or "").lower()
    for k, v in SETS.items():
        if k in low:
            return v
    return None


def main():
    m = sqlite3.connect(f"file:{MKT}?mode=ro", uri=True)
    s = sqlite3.connect(f"file:{SAL}?mode=ro", uri=True)
    today = m.execute("SELECT MAX(date) FROM vibes_price_history WHERE source='dyli'").fetchone()[0]
    # price lookup: normalized name -> floor (variant-tagged rows, use as-is)
    floors = {}
    for nm, p in m.execute("SELECT name, market_price FROM vibes_price_history "
                           "WHERE source='dyli' AND date=? AND market_price>0", (today,)):
        floors[re.sub(r"[^a-z0-9]+", " ", nm.lower()).strip()] = p

    def floor_of(pull_name):
        key = re.sub(r"[^a-z0-9]+", " ", (pull_name or "").lower()).strip()
        if key in floors:
            return floors[key]
        hits = [v for k, v in floors.items() if key[:40] and key[:40] in k]
        return sorted(hits)[len(hits) // 2] if hits else None

    pulls = s.execute("SELECT name, price FROM dyli_pulls WHERE LOWER(brand)='vibes' "
                      "AND name NOT LIKE '%Fair Drop%' AND LOWER(name) NOT LIKE '%booster box%' "
                      "AND LOWER(name) NOT LIKE '%case%' AND LOWER(name) NOT LIKE '%deck%' "
                      "AND LOWER(name) NOT LIKE '%bundle%'").fetchall()
    per_set = {}
    for nm, listed in pulls:
        st = set_of(nm)
        if not st:
            continue
        val = floor_of(nm) or listed or 0
        per_set.setdefault(st, []).append((nm, val))

    print(f"═══ VIBES PACK EV — from {sum(len(v) for v in per_set.values())} observed pulls "
          f"(prices as of {today}) ═══")
    packs = {"Legend of the Lils": "legend of the lils booster pack",
             "Enter the Huddle": "enter the huddle booster pack",
             "Birb & Pengu": "birb pengu booster pack"}
    for st, vals in sorted(per_set.items(), key=lambda x: -len(x[1])):
        n = len(vals)
        ev = sum(v for _, v in vals) / n if n else 0
        pk = [p for k, p in floors.items()
              if all(w in k for w in packs.get(st, "zzz").split()[:3])
              and "pack" in k and "box" not in k and "case" not in k and p >= 1.0]
        pack_floor = sorted(pk)[0] if pk else None   # cheapest SANE pack listing
        tag = "" if n >= MIN_PULLS else f"  ⚠️ n={n} < {MIN_PULLS}: ANECDOTE, not estimate"
        print(f"\n  {st}: n={n} pulls | EV/pull ≈ ${ev:.2f}{tag}")
        if pack_floor:
            print(f"    pack floor ${pack_floor} → EV ratio {ev/pack_floor:.2f}x "
                  f"({'+' if ev > pack_floor else '-'}EV to rip at floor)")
        best = sorted(vals, key=lambda x: -(x[1] or 0))[:3]
        for nm, v in best:
            print(f"    best observed: ${v} {nm[:52]}")


if __name__ == "__main__":
    main()
