#!/usr/bin/env python3
"""
vibes_market_report.py — the daily consolidated Vibes TCG market intelligence
report. Ties every collection layer together into one read:

  1. SELL-OUTS + sell-through velocity (supply deltas)
  2. LADDER ANOMALIES (foil priced under common = fake floors / mispricings)
  3. RAW-vs-SLAB premiums (variant x grade two-dimensional model)
  4. Tightest BID/ASK spreads (liquidity signal)
  5. Real movers (variant-clean, ladder-sane only)
  6. Sales tape + pull counts (24h)

Cron: 4:35am daily (after ingest 4:10 + eBay 4:20), appends to
~/logs/vibes_market_report.log. Also runnable ad-hoc. Zero API calls — pure
derivation from data already collected. Output doubles as source material for
the Studio's Market Intelligence page (and, eventually, Glitch's dry takes).
"""
import os, sqlite3
from datetime import datetime

MKT = os.path.expanduser("~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite")
SAL = os.path.expanduser("~/Documents/undesirables-mcp-server/.cache/dyli_sales.sqlite")


def main():
    m = sqlite3.connect(f"file:{MKT}?mode=ro", uri=True)
    s = sqlite3.connect(f"file:{SAL}?mode=ro", uri=True)
    today = m.execute("SELECT MAX(date) FROM vibes_price_history WHERE source='dyli'").fetchone()[0]
    prev = m.execute("SELECT MAX(date) FROM vibes_price_history WHERE source='dyli' AND date<?", (today,)).fetchone()[0]
    print(f"\n════ VIBES MARKET REPORT — {today} (vs {prev}) ════")

    # 1. sell-outs + sell-through
    souts = m.execute("""SELECT a.name FROM vibes_price_history a JOIN vibes_price_history b
        ON a.product_id=b.product_id AND b.source='dyli' AND b.date=?
        WHERE a.source='dyli' AND a.date=? AND COALESCE(a.supply,0)=0 AND COALESCE(b.supply,0)>0""",
        (prev, today)).fetchall()
    print(f"\n■ SELL-OUTS today: {len(souts)}")
    for (nm,) in souts[:5]:
        print(f"   - {nm[:64]}")
    vel = m.execute("""SELECT a.name, b.supply-a.supply, a.supply, a.market_price
        FROM vibes_price_history a JOIN vibes_price_history b
        ON a.product_id=b.product_id AND b.source='dyli' AND b.date=?
        WHERE a.source='dyli' AND a.date=? AND b.supply>a.supply AND a.supply IS NOT NULL
        ORDER BY (b.supply-a.supply) DESC LIMIT 5""", (prev, today)).fetchall()
    if vel:
        print("■ FASTEST SELL-THROUGH (units moved / left / floor):")
        for nm, mv, left, fp in vel:
            print(f"   {mv:>3} moved | {left:>4} left | ${fp:<8} {nm[:48]}")

    # 2. ladder anomalies
    an = m.execute("""WITH latest AS (SELECT * FROM vibes_price_history WHERE source='dyli'
          AND date=? AND market_price>0 AND grader IS NULL)
        SELECT c.base_key, c.market_price, f.market_price FROM latest c
        JOIN latest f ON c.base_key=f.base_key AND c.sub_type='Common' AND f.sub_type IN ('Foil','Arctic Foil')
        WHERE f.market_price < c.market_price AND c.market_price >= 5 LIMIT 5""", (today,)).fetchall()
    print(f"\n■ LADDER ANOMALIES (foil under common — fake floor or genuine mispricing): {len(an)}")
    for bk, cp, fp in an:
        print(f"   {bk[:44]:<44} common ${cp} > foil ${fp}")

    # 3. raw-vs-slab premiums (top, where both sides exist)
    prem = m.execute("""WITH latest AS (SELECT * FROM vibes_price_history WHERE source='dyli'
          AND date=? AND market_price>0)
        SELECT g.grader, g.grade_num, g.base_key, g.sub_type, g.market_price, r.market_price
        FROM latest g JOIN latest r ON g.base_key=r.base_key AND g.sub_type=r.sub_type
          AND r.grader IS NULL AND g.grader IS NOT NULL
        ORDER BY g.market_price/r.market_price DESC LIMIT 5""", (today,)).fetchall()
    if prem:
        print("\n■ RAW→SLAB PREMIUMS (grading-ROI signal):")
        for gr, gn, bk, v, sp, rp in prem:
            print(f"   {gr} {gn:.0f} [{v}] {bk[:30]:<30} ${rp} raw → ${sp} slab ({sp/rp:.0f}x)")

    # 4. tightest bid/ask (liquidity)
    ba = m.execute("""SELECT name, highest_bid, market_price,
        ROUND((market_price-highest_bid)*100.0/market_price,1)
        FROM vibes_price_history WHERE source='dyli' AND date=? AND highest_bid>0
        AND market_price>highest_bid AND market_price>=5
        ORDER BY (market_price-highest_bid)/market_price ASC LIMIT 5""", (today,)).fetchall()
    if ba:
        print("\n■ TIGHTEST BID/ASK (most liquid):")
        for nm, hb, mp, sp in ba:
            print(f"   {sp:>5}% spread | bid ${hb} / ask ${mp} | {nm[:44]}")

    # 5. real movers (ladder-sane: exclude cards flagged as anomalies)
    bad_keys = {r[0] for r in an}
    mv = m.execute("""SELECT a.name, a.base_key, b.market_price, a.market_price
        FROM vibes_price_history a JOIN vibes_price_history b
        ON a.product_id=b.product_id AND b.source='dyli' AND b.date=?
        WHERE a.source='dyli' AND a.date=? AND b.market_price>=2 AND a.market_price>0
        AND ABS(a.market_price-b.market_price)/b.market_price>0.15
        ORDER BY ABS(a.market_price-b.market_price)/b.market_price DESC LIMIT 8""",
        (prev, today)).fetchall()
    real = [(nm, p0, p1) for nm, bk, p0, p1 in mv if bk not in bad_keys][:5]
    if real:
        print("\n■ REAL MOVERS (day-over-day, ladder-sane):")
        for nm, p0, p1 in real:
            print(f"   {(p1-p0)/p0*100:+6.0f}% ${p0} → ${p1} | {nm[:46]}")

    # 6. tape (24h)
    sales = s.execute("SELECT COUNT(*), ROUND(SUM(price),2) FROM dyli_sales_events "
                      "WHERE is_vibes=1 AND is_fair_drop=0 AND event_date>=datetime('now','-1 day')").fetchone()
    pulls = s.execute("SELECT COUNT(*) FROM dyli_pulls WHERE LOWER(brand)='vibes' "
                      "AND pulled_at>=datetime('now','-1 day')").fetchone()[0]
    print(f"\n■ 24H TAPE: {sales[0]} sales (${sales[1] or 0}) | {pulls} pack pulls")
    print(f"════ report generated {datetime.now().isoformat(timespec='seconds')} ════")


if __name__ == "__main__":
    main()
