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

    # 3b) nightly-job freshness — a job can die at python STARTUP (2026-07-16:
    # transient TCC denial killed the 04:00 conformal refit instantly; in-script
    # alerting never ran and this healthcheck stayed green). Check each job's
    # OUTPUT artifact instead of trusting silence.
    try:
        import json
        X402 = os.path.expanduser("~/Documents/undesirables-x402-server")
        fit = json.load(open(os.path.join(X402, "conformal_offsets.json"))).get("fit_date", "")
        log(f"  conformal offsets fit_date: {fit}")
        if fit < TODAY.isoformat():        # 04:00 refit ran before this 07:00 check
            problems.append(f"conformal refit MISSED: offsets fit_date={fit} (expected {TODAY})")
    except Exception as e:
        problems.append(f"conformal offsets unreadable: {str(e)[:50]}")
    # NOTE: never use a job's LOG mtime as its artifact — cron's `>> log 2>&1`
    # redirect refreshes the log even when bash/python dies at spawn (the exact
    # failure class we're guarding). Use true OUTPUTS: written files / git HEAD.
    for label, path, max_h in (
        ("ACI adjust weights (05:25)", os.path.join(os.path.expanduser("~/Documents/undesirables-x402-server"), "aci_adjust.json"), 26),
        ("Shroomy kaggle archiver (hourly loop)", os.path.expanduser("~/logs/kaggle_archiver.log"), 3),
    ):
        try:
            age_h = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))).total_seconds() / 3600
            log(f"  {label}: artifact touched {age_h:.1f}h ago")
            if age_h > max_h:
                problems.append(f"{label} STALE: artifact {age_h:.0f}h old (max {max_h}h)")
        except OSError as e:
            problems.append(f"{label} artifact missing: {str(e)[:40]}")
    # ── ON-CHAIN PUSHERS (added 2026-07-18 after the Casper wallet ran dry
    # unnoticed for 66 hourly pushes — "all green" must include these).
    # Rule: healthy iff the log was written recently AND its tail ends in the
    # job's success marker (a failing job appends too, so mtime alone lies).
    for label, path, max_h, ok_markers in (
        ("LitVM oracle v2 (hourly)", "~/logs/litvm_updater_v2.log", 2, ("✅ Confirmed", "Done")),
        ("Weather merkle (hourly)", "~/logs/weather_merkle_err.log", 2, ("Root committed", "Done.")),
        ("Mantle oracle v2 (hourly)", "~/logs/mantle_updater_v2.log", 2, ("Confirmed", "Done")),
        ("Mantle merkle (hourly)", "~/logs/mantle_merkle_updater.log", 2, ("Done",)),
        ("Casper merkle (hourly)", "~/logs/casper_merkle_updater.log", 2, ("deploy_hash",)),
        ("LitVM price merkle (hourly)", "~/logs/merkle_updater.log", 2, ("Done",)),
        ("Mantle weather (hourly)", "~/logs/mantle_weather.log", 2, ("Done.",)),
        ("Weather worker predictions (hourly)", "~/logs/oracle_worker.log", 2, ()),  # mtime-only: quiet runs log nothing distinctive
    ):
        p = os.path.expanduser(path)
        try:
            age_h = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(p))).total_seconds() / 3600
            with open(p, "rb") as f:
                f.seek(max(0, os.path.getsize(p) - 4000))
                tail = f.read().decode("utf-8", "replace")
            ok = age_h <= max_h and (not ok_markers or any(m in tail for m in ok_markers))
            log(f"  {label}: {'OK' if ok else 'PROBLEM'} (log {age_h:.1f}h old)")
            if not ok:
                problems.append(f"{label}: log {age_h:.1f}h old / no success marker in tail — check {path}")
        except OSError:
            problems.append(f"{label}: log missing ({path})")

    # LitVM wallet runway (burn ≈0.00001/hr @ 0.01 gwei → years; cheap insurance)
    try:
        import json
        req = urllib.request.Request("https://liteforge.rpc.caldera.xyz/http",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
                             "params": ["0x77B82Fe7ADD725017E106CFE6E26Dc8b37C93Fca", "latest"]}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "undesirables-healthcheck/1.0"})
        wei = int(json.load(urllib.request.urlopen(req, timeout=15))["result"], 16)
        log(f"  LitVM pusher wallet: {wei/1e18:.4f} gas token")
        if wei / 1e18 < 0.01:
            problems.append(f"LitVM pusher wallet LOW: {wei/1e18:.4f} — top up before hourly pushes stall")
    except Exception as e:
        log(f"  LitVM balance check skipped ({str(e)[:40]})")

    # Casper oracle wallet runway — ran dry unnoticed for 66 hourly pushes
    # (~Jul 15-18); net cost ≈5.14 CSPR/push ≈123/day. Alert at <900 CSPR
    # (~7 days) so a faucet top-up happens before the roots go stale.
    try:
        import json
        req = urllib.request.Request("http://127.0.0.1:7777/rpc",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "query_balance",
                "params": {"purse_identifier": {"main_purse_under_public_key":
                    "0202e5e6d06926853408f5cbe3021c2245c67a864094ee2cb70a1687d086cd25655f"}}}).encode(),
            headers={"Content-Type": "application/json"})
        cspr = int(json.load(urllib.request.urlopen(req, timeout=15))["result"]["balance"]) / 1e9
        log(f"  Casper oracle wallet: {cspr:,.0f} CSPR (~{cspr/123:.0f} days of hourly pushes)")
        if cspr < 900:
            problems.append(f"Casper wallet LOW: {cspr:,.0f} CSPR (~{cspr/123:.0f} days left) — top up from the testnet faucet")
    except Exception as e:
        problems.append(f"Casper balance check failed: {str(e)[:50]}")

    # forecast_feed.json — the FREE board the site + agents consume (04:50 cron)
    try:
        ff = os.path.join(os.path.expanduser("~/Documents/undesirables-x402-server"), "forecast_feed.json")
        age_h = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(ff))).total_seconds() / 3600
        log(f"  forecast feed (04:50): regenerated {age_h:.1f}h ago")
        if age_h > 26:
            problems.append(f"forecast feed STALE: {age_h:.0f}h old — site + free agents are serving old grades")
    except OSError:
        problems.append("forecast_feed.json missing")

    # preimage backup: the artifact is the backup REPO's latest commit
    try:
        import subprocess
        ts = int(subprocess.run(
            ["git", "-C", os.path.expanduser("~/Documents/undesirables-oracle-preimages"),
             "log", "-1", "--format=%ct"], capture_output=True, text=True, timeout=15).stdout.strip())
        age_h = (datetime.now().timestamp() - ts) / 3600
        log(f"  preimage backup (05:20): last repo commit {age_h:.1f}h ago")
        if age_h > 26:
            problems.append(f"preimage backup STALE: last commit {age_h:.0f}h ago (max 26h)")
    except Exception as e:
        problems.append(f"preimage backup repo unreadable: {str(e)[:40]}")

    # 4) Bazaar 30-day recency filter (x402 market research 2026-07-14):
    # resources with no settled payment in 30d are silently DROPPED from the
    # CDP Bazaar index. AUTHORITATIVE clock = the Bazaar's own
    # quality.lastCalledAt (local memory was 11 days off when checked Jul-14).
    # Primary defense: scripts/bazaar_keepalive.py auto-sweeps at 21d; this
    # alarm at 25d is the backstop if the keepalive itself breaks.
    try:
        import json
        req = urllib.request.Request(
            "https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant"
            "?payTo=0x642e8a7C289381f24f0395e0539f0bA41c74Cc1B",
            headers={"User-Agent": "undesirables-healthcheck/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        items = d.get("items") or d.get("resources") or []
        stamps = [i["quality"]["lastCalledAt"] for i in items
                  if (i.get("quality") or {}).get("lastCalledAt")]
        if len(items) < 12:
            problems.append(f"Bazaar index: only {len(items)} of 12 resources listed — some were dropped")
        if stamps:
            oldest = min(date.fromisoformat(s[:10]) for s in stamps)
            settle_age = (TODAY - oldest).days
            log(f"  Bazaar recency: {len(items)} listed; stalest settle {oldest} ({settle_age}d ago; drop at 30d)")
            if settle_age >= 25:
                problems.append(
                    f"Bazaar recency: stalest listing {settle_age}d unpaid (drop at 30d) — "
                    f"the keepalive should have swept at 21d; run x402_smoke sweep + check bazaar_keepalive.log")
        else:
            problems.append("Bazaar recency: no lastCalledAt data on any listing")
    except Exception as e:
        problems.append(f"Bazaar recency check failed: {str(e)[:50]}")

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
