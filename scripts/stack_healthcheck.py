#!/usr/bin/env python3
"""
stack_healthcheck.py — one nightly guard over the WHOLE data-aggregation stack.

WHY: on 2026-07-08 the Vibes DYLI ingest had been silently dead for 3 DAYS
(broken INSERT, no alarm) — found only by a manual audit. Only the DYLI feed
and (since 07-11) the preimage backup had dead-man's alarms; the other ~8
streams failed into the void. This checks every store's freshness against its
expected cadence + a few structural invariants, and fires ONE ntfy phone alert
listing everything stale/broken. Silence = healthy.

Read-only on all DBs; stdlib only; zero API cost. Cron: 07:00 daily (after the
full nightly choreography has finished ~06:30).
"""
import os, sqlite3, urllib.request
from datetime import date, datetime, timedelta

MCP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MKT = os.path.join(MCP, ".cache", "market_memory.sqlite")
SAL = os.path.join(MCP, ".cache", "dyli_sales.sqlite")
X = os.path.expanduser("~/Documents/undesirables-x402-server")
LOG = os.path.expanduser("~/logs/stack_healthcheck.log")
TODAY = date.today()


def env(k):
    for line in open(os.path.join(X, ".env")):
        if line.startswith(k + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(k)


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def days_old(datestr):
    """Whole days between a YYYY-MM-DD (or ISO ts) string and today."""
    if not datestr:
        return 9999
    try:
        d = datetime.fromisoformat(str(datestr)[:19]).date() if "T" in str(datestr) or ":" in str(datestr) else date.fromisoformat(str(datestr)[:10])
    except Exception:
        return 9999
    return (TODAY - d).days


def main():
    problems = []

    # ── freshness checks: (label, latest-value-getter, max allowed age in days) ──
    m = ro(MKT)
    q1 = lambda s: m.execute(s).fetchone()[0]
    checks = [
        ("TCGCSV price pipeline", q1("SELECT MAX(date) FROM price_history WHERE product_id<9500000"), 1),
        ("Vibes DYLI catalog", q1("SELECT MAX(date) FROM vibes_price_history WHERE source='dyli'"), 1),
        ("Vibes eBay tracker", q1("SELECT MAX(date) FROM vibes_ebay_history"), 1),
        ("graded_prices enrichment", q1("SELECT MAX(fetched_at) FROM graded_prices"), 1),
    ]
    s = ro(SAL)
    checks.append(("DYLI sales/pulls poller", s.execute("SELECT MAX(captured_at) FROM dyli_sales_events").fetchone()[0], 1))
    try:
        fl = ro(os.path.join(X, "forecast_ledger.sqlite"))
        checks.append(("forecast ledger", fl.execute("SELECT MAX(forecast_date) FROM forecast_ledger").fetchone()[0], 2))
    except Exception as e:
        problems.append(f"forecast_ledger unreadable: {str(e)[:50]}")

    for label, latest, max_age in checks:
        age = days_old(latest)
        status = "OK" if age <= max_age else f"STALE {age}d (max {max_age})"
        log(f"  {label}: latest={str(latest)[:19]} → {status}")
        if age > max_age:
            problems.append(f"{label} STALE {age}d (latest {str(latest)[:10]})")

    # ── structural invariants (the bug classes that have actually bitten us) ──
    # 1) TCGCSV row-count cliff (a half-loaded pipeline)
    rows_today = q1("SELECT COUNT(*) FROM price_history WHERE product_id<9500000 AND date=(SELECT MAX(date) FROM price_history WHERE product_id<9500000)")
    if rows_today < 250000:
        problems.append(f"TCGCSV row cliff: only {rows_today:,} rows on latest date (expect ~281k)")
    log(f"  TCGCSV latest-date rows: {rows_today:,}")

    # 2) soul predictions committed on-chain (the Jul-31 load-bearing chain)
    try:
        sp = ro(os.path.join(X, "soul_predictions.sqlite"))
        uncommitted = sp.execute("SELECT COUNT(*) FROM merkle_roots WHERE tx_hash IS NULL").fetchone()[0]
        if uncommitted:
            problems.append(f"{uncommitted} weekly soul root(s) NOT committed on-chain")
        log(f"  soul roots on-chain: {sp.execute('SELECT COUNT(*) FROM merkle_roots').fetchone()[0]} committed, {uncommitted} pending")
    except Exception as e:
        problems.append(f"soul_predictions unreadable: {str(e)[:50]}")

    # 3) oracle health endpoint
    try:
        import json
        h = json.load(urllib.request.urlopen("http://127.0.0.1:8402/health", timeout=10))
        if h.get("status") != "ok":
            problems.append(f"oracle /health status={h.get('status')}")
        log(f"  oracle /health: {h.get('status')} ({h.get('total_cards')} cards)")
    except Exception as e:
        problems.append(f"oracle /health unreachable: {str(e)[:50]}")

    # ── verdict + single phone alert ──
    if problems:
        body = f"{len(problems)} STACK ISSUE(S):\n" + "\n".join(f"• {p}" for p in problems)
        log("❌ " + body.replace("\n", " | "))
        topic = env("NTFY_TOPIC")
        if topic:
            try:
                urllib.request.urlopen(urllib.request.Request(
                    f"https://ntfy.sh/{topic}", data=body.encode(),
                    headers={"Title": "Undesirables stack health", "Priority": "high", "Tags": "rotating_light"}),
                    timeout=15)
                log("  (phone alert sent)")
            except Exception as e:
                log(f"  (ntfy failed: {e})")
    else:
        log("✅ ALL GREEN — every data stream fresh, invariants hold, roots committed, oracle up.")


if __name__ == "__main__":
    main()
