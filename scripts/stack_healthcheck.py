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
import os, sqlite3, time, urllib.request
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


# 2026-07-28: set NO_PAGE=1 when deliberately triggering an alarm to verify it
# fires. On 07-28 I tested the ownership alarm by corrupting its baseline and
# sent sailorpepe two high-priority pages saying his signing key might be
# compromised and his contracts might already be lost. Nothing was wrong. An
# alarm that cannot be exercised without paging a human will either go untested
# or train him to ignore the phone; both are worse than the bug it watches for.
NO_PAGE = os.environ.get("NO_PAGE") == "1"


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
        # Base mirror (added 2026-07-27). LiteForge is a testnet: if it resets,
        # the mainnet copy is the only surviving proof that a prediction preceded
        # its outcome. A root sitting un-mirrored past the contract's 10-day
        # window can NEVER be mirrored, so this is a deadline, not a nag.
        try:
            base_pending = sp.execute(
                "SELECT as_of FROM merkle_roots WHERE base_tx_hash IS NULL "
                "ORDER BY as_of").fetchall()
            if base_pending:
                ages = []
                for (as_of,) in base_pending:
                    age = (TODAY - date.fromisoformat(as_of)).days
                    ages.append(f"{as_of} ({age}d, {10 - age}d left)"
                                if age <= 10 else f"{as_of} (LOST, {age}d)")
                problems.append(
                    f"soul root(s) not mirrored to Base: {', '.join(ages)}. "
                    f"Past 10 days the Base contract refuses them permanently — "
                    f"run soul_predictions.py commit_onchain()")
            else:
                log("  soul Base mirror: all roots accounted for")
        except Exception as e:
            problems.append(f"soul Base mirror check FAILED: {str(e)[:60]}")
    except Exception as e:
        problems.append(f"soul_predictions unreadable: {str(e)[:50]}")

    # 2b) price proof-tree Base mirror parity (contract deployed 2026-07-31).
    # The 286K-product proof tree is what the public "hash it" story rests on;
    # its Base twin exists precisely so a LiteForge reset can't erase it. The
    # mirror leg in merkle_root_updater.py is deliberately non-blocking, so
    # THIS is the check that catches silent drift. Base lagging LiteForge by
    # one root (mirror tx failed once) is a warning; the updater's next push
    # self-heals it — persistent mismatch means the mirror leg is broken.
    try:
        import json as _mj
        from web3 import Web3 as _MW3
        _mabi = _mj.load(open(os.path.join(X, "MerklePriceOracle_abi.json")))
        _lf_addr = _mj.load(open(os.path.join(X, "merkle_deployment.json")))["contract_address"]
        _ba_addr = _mj.load(open(os.path.join(X, "merkle_deployment_base.json")))["contract"]
        _lfw = _MW3(_MW3.HTTPProvider("https://liteforge.rpc.caldera.xyz/http",
                                      request_kwargs={"timeout": 30}))
        _baw = _MW3(_MW3.HTTPProvider(
            f"https://base-mainnet.g.alchemy.com/v2/{env('ALCHEMY_API_KEY')}",
            request_kwargs={"timeout": 30}))
        _lfr = _lfw.eth.contract(address=_lf_addr, abi=_mabi).functions.merkleRoot().call().hex()
        _bar = _baw.eth.contract(address=_ba_addr, abi=_mabi).functions.merkleRoot().call().hex()
        if _lfr == _bar:
            log(f"  price proof-tree Base mirror: roots match ({_lfr[:14]}…)")
        else:
            problems.append(
                f"price proof-tree MIRROR DRIFT: LiteForge {_lfr[:14]}… vs Base "
                f"{_bar[:14]}… — check merkle_root_updater.py's Base leg "
                f"(non-blocking by design, so it fails quiet)")
    except Exception as e:
        problems.append(f"price proof-tree Base mirror check FAILED: {str(e)[:60]}")

    # 2c) graded proof-tree Base mirror parity (contract deployed 2026-08-09).
    # Same rationale as 2b: the graded tree backs the PAID /api/v1/graded/proof
    # surface, and its mirror leg in graded_merkle_updater.py is non-blocking,
    # so this is the check that catches silent drift. One-root lag self-heals
    # on the next daily push (05:17); persistent mismatch = broken mirror leg.
    try:
        import json as _gj
        from web3 import Web3 as _GW3
        _gabi = _gj.load(open(os.path.join(X, "GradedPriceOracle_abi.json")))
        _glf = _gj.load(open(os.path.join(X, "graded_deployment.json")))["contract"]
        _gba = _gj.load(open(os.path.join(X, "graded_deployment_base.json")))["contract"]
        _glfw = _GW3(_GW3.HTTPProvider("https://liteforge.rpc.caldera.xyz/http",
                                       request_kwargs={"timeout": 30}))
        _gbaw = _GW3(_GW3.HTTPProvider(
            f"https://base-mainnet.g.alchemy.com/v2/{env('ALCHEMY_API_KEY')}",
            request_kwargs={"timeout": 30}))
        _glfr = _glfw.eth.contract(address=_glf, abi=_gabi).functions.merkleRoot().call().hex()
        _gbar = _gbaw.eth.contract(address=_gba, abi=_gabi).functions.merkleRoot().call().hex()
        if _glfr == _gbar:
            log(f"  graded proof-tree Base mirror: roots match ({_glfr[:14]}…)")
        else:
            problems.append(
                f"graded proof-tree MIRROR DRIFT: LiteForge {_glfr[:14]}… vs Base "
                f"{_gbar[:14]}… — check graded_merkle_updater.py's Base leg "
                f"(non-blocking by design, so it fails quiet)")
    except Exception as e:
        problems.append(f"graded proof-tree Base mirror check FAILED: {str(e)[:60]}")

    # 3) oracle health endpoint.
    # RETRIES (added 2026-08-04): this probe is LOOPBACK and normally answers in
    # ~2ms, but it runs at the END of a 6-minute healthcheck and the whole box
    # can be CPU/memory-starved by then — that morning a runaway Messages.app
    # (100% CPU since boot) + ~22GB of swapouts made a 127.0.0.1 request miss a
    # 10s timeout, paging sailorpepe for a server that was serving fine (zero
    # slow requests in oracle_requests.jsonl, nothing in the cloudflared log).
    # A single loopback timeout is evidence about the HOST, not the service, so
    # only alarm when it fails repeatedly — and say so, to point the next
    # session at host contention instead of the oracle.
    _h_err = None
    for _attempt in range(3):
        try:
            import json
            h = json.load(urllib.request.urlopen("http://127.0.0.1:8402/health", timeout=10))
            if h.get("status") != "ok":
                problems.append(f"oracle /health status={h.get('status')}")
            log(f"  oracle /health: {h.get('status')} ({h.get('total_cards')} cards)"
                + (f" [recovered after {_attempt} retr{'y' if _attempt == 1 else 'ies'}"
                   f" — host was starved, check CPU/swap]" if _attempt else ""))
            _h_err = None
            break
        except Exception as e:
            _h_err = str(e)[:50]
            if _attempt < 2:
                time.sleep(5)
    if _h_err:
        problems.append(
            f"oracle /health unreachable on 3 tries: {_h_err} — loopback probe, so "
            f"check host CPU/swap (ps -Ao %cpu,comm -r | head; sysctl vm.swapusage) "
            f"before suspecting the oracle")

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
    # Mantle + Casper pushers were REMOVED from this list 2026-07-21 when their
    # crons were disabled — the DoraHacks competition they were built for ended.
    # Dropping the jobs without dropping their checks would have traded four
    # silent jobs for a nightly false alarm, which is strictly worse. LitVM
    # stays: LiteForge is the live chain.
    # ── ON-CHAIN PUSHERS (added 2026-07-18 after the Casper wallet ran dry
    # unnoticed for 66 hourly pushes — "all green" must include these).
    # Rule: healthy iff the log was written recently AND its tail ends in the
    # job's success marker (a failing job appends too, so mtime alone lies).
    for label, path, max_h, ok_markers in (
        ("LitVM oracle v2 (hourly)", "~/logs/litvm_updater_v2.log", 2, ("✅ Confirmed", "Done")),
        ("Weather merkle (hourly)", "~/logs/weather_merkle_err.log", 2, ("Root committed", "Done.")),
        ("LitVM price merkle (hourly)", "~/logs/merkle_updater.log", 2, ("Done",)),
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

    # Casper wallet-runway check REMOVED 2026-07-21 with the wind-down: it
    # queried the local casper-proxy on :7777, which is now unloaded, so it
    # alarmed the moment the proxy stopped — exactly the false alarm this
    # change existed to avoid. Nothing is pushing to Casper any more, so
    # there is no runway to protect. (Kept for history: the wallet ran dry
    # unnoticed for 66 pushes ~Jul 15-18 at ~5.14 CSPR/push.)

    # ── INDEXABILITY (weekly, Mondays) — the CDP validator is the AUTHORITY on
    # whether the Bazaar will index us. It returned valid=false on 2026-07-14
    # while every internal view looked fine (graceful-402 was dropping the
    # payment-required header for non-SDK UAs) and cost us weeks of invisibility.
    # An internal check proves what we EMIT; only this proves we're INDEXABLE.
    # Alarms only on an explicit valid=false / failed check — an unreachable CDP
    # is logged and skipped so their outage never becomes our false alarm.
    if TODAY.weekday() == 0:
        try:
            import json
            req = urllib.request.Request(
                "https://api.cdp.coinbase.com/platform/v2/x402/validate",
                data=json.dumps({"resource": "https://oracle.the-undesirables.com/api/v1/simulate"}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "undesirables-healthcheck/1.0"})
            v = json.load(urllib.request.urlopen(req, timeout=45))
            pf = v.get("preflight") or []
            failed = [c.get("check") for c in pf if not c.get("passed")]
            active = (v.get("index") or {}).get("active")
            log(f"  CDP indexability (weekly): valid={v.get('valid')} "
                f"preflight={sum(1 for c in pf if c.get('passed'))}/{len(pf)} index.active={active}")
            if not v.get("valid"):
                problems.append(f"CDP validator says NOT INDEXABLE (valid=false) — failed: {failed[:4]}")
            elif failed:
                problems.append(f"CDP validator preflight failures: {failed[:4]}")
            elif active is False:
                problems.append("CDP validator: index.active=false — we are dropped from the Bazaar index")
        except Exception as e:
            log(f"  CDP indexability: skipped (validator unreachable: {str(e)[:50]})")

    # Hosted MCP endpoint (https://mcp.the-undesirables.com — root URL; /mcp
    # is an alias. launchd com.undesirables.
    # mcp-remote on :8443). Deliberately a SEPARATE failure domain from the paid
    # oracle — so it needs its own check or it can die unnoticed. A plain GET
    # returns 406 (MCP requires specific Accept headers); 406 or 200 means the
    # tunnel + service are alive. 421 = the Invalid-Host-header regression.
    try:
        code = urllib.request.urlopen(
            urllib.request.Request("https://mcp.the-undesirables.com",
                                   headers={"User-Agent": "undesirables-healthcheck/1.0"}),
            timeout=20).getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        code = None
        problems.append(f"hosted MCP endpoint unreachable: {str(e)[:50]}")
    if code is not None:
        log(f"  hosted MCP endpoint: HTTP {code}")
        if code not in (200, 406):
            problems.append(f"hosted MCP endpoint returned {code} (expect 406/200; 421 = Invalid Host header)")

    # ── PUBLISHED CLAIMS vs REALITY (added 2026-07-22) ──
    # Every incident this month was an unverified claim outliving the code: the
    # Kaggle dataset 3 weeks stale, /docs headlining a model we don't default to,
    # "10 tools" after shipping 12, a hardcoded total_endpoints of 27 that was
    # never right. Numbers we can DERIVE are now derived (the oracle root and the
    # MCP landing page count themselves). This watches the ones that can't be —
    # it compares what we ADVERTISE against what we actually serve, so drift
    # pages us instead of being found by a human reading a file months later.
    try:
        import json
        root = json.load(urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8402/", headers={"User-Agent": "Mozilla/5.0 healthcheck"}), timeout=20))
        adv_total = root.get("total_endpoints")
        adv_cards = root.get("total_products")
        listed = len(root["endpoints"]["free"]) + len(root["endpoints"]["paid"])
        live_cards = json.load(urllib.request.urlopen(
            "http://127.0.0.1:8402/health", timeout=20)).get("total_cards")
        log(f"  published claims: {adv_total} endpoints advertised / {listed} listed; "
            f"{adv_cards:,} products advertised / {live_cards:,} live")
        if adv_total != listed:
            problems.append(f"claim drift: root advertises {adv_total} endpoints but lists {listed}")
        # tolerate a day of DB growth; flag a real divergence
        if adv_cards and live_cards and abs(adv_cards - live_cards) > 5000:
            problems.append(f"claim drift: advertises {adv_cards:,} products, DB has {live_cards:,}")
        tag = root.get("tagline", "")
        if adv_cards and f"{adv_cards // 1000}K" not in tag:
            problems.append(f"claim drift: tagline card count disagrees with {adv_cards:,}")

        # Cross-check the SITE against this server. The oracle can be perfectly
        # self-consistent while the site advertises different numbers — that is
        # exactly how "19 free endpoints" survived the 2026-07-22 sweep (I only
        # checked the oracle's internal consistency; the Studio caught the site
        # by hand). The site is a STATIC file that cannot compute, so it is the
        # surface most likely to rot, and it is the one agents read first.
        try:
            site = urllib.request.urlopen(urllib.request.Request(
                "https://the-undesirables.com/llms.txt",
                headers={"User-Agent": "undesirables-healthcheck/1.0"}), timeout=25).read().decode("utf-8", "replace")
            import re as _re
            m_paid = _re.search(r"(\d+)\s+paid endpoints", site)
            m_free = _re.search(r"(\d+)\s+free endpoints", site)
            site_paid = int(m_paid.group(1)) if m_paid else None
            site_free = int(m_free.group(1)) if m_free else None
            log(f"  site llms.txt claims: {site_paid} paid / {site_free} free "
                f"(oracle serves {len(root['endpoints']['paid'])} / {len(root['endpoints']['free'])})")
            if site_paid is not None and site_paid != len(root["endpoints"]["paid"]):
                problems.append(f"SITE claim drift: llms.txt says {site_paid} paid, oracle serves "
                                f"{len(root['endpoints']['paid'])} — site fix (Studio/Vercel)")
            if site_free is not None and site_free != len(root["endpoints"]["free"]):
                problems.append(f"SITE claim drift: llms.txt says {site_free} free, oracle serves "
                                f"{len(root['endpoints']['free'])} — site fix (Studio/Vercel)")
        except Exception as e:
            log(f"  site claims cross-check skipped ({str(e)[:40]})")
    except Exception as e:
        problems.append(f"published-claims check failed: {str(e)[:50]}")

    # --- route table vs advertised surfaces --------------------------------
    # 2026-07-30. GET /api/v1/wallet/portfolio was a LIVE route returning 200
    # with no paywall, described in openapi as "$0.25", and present in NEITHER
    # the root listing nor the x402 manifest. Three callers got it free.
    #
    # Every check above compares one advertised number against another
    # advertised number, so a route missing from BOTH surfaces is invisible to
    # all of them — the counts agreed with each other perfectly. The only
    # witness that cannot be fooled is the app's own route table. This diffs
    # openapi.json (what the app actually serves) against root + manifest (what
    # we tell people we serve) and fails on a gap in either direction: a route
    # we don't advertise, or an advertised path that isn't a route.
    try:
        import json
        spec = json.load(urllib.request.urlopen(
            "http://127.0.0.1:8402/openapi.json", timeout=25))
        # /chart/{product_id}.png is advertised and real but sits outside
        # /api/v1, so an /api/v1-only view of the route table reports it as a
        # phantom. Take every documented path and subtract only the plumbing.
        NOT_PRODUCT = {
            "/api/v1/ebay/deletion",   # eBay's account-deletion compliance
                                       # webhook — eBay calls it, nobody else
                                       # should, and listing it invites noise
        }
        real = {p for p in spec["paths"]
                if (p.startswith("/api/v1/") or p.startswith("/chart/"))
                and p not in NOT_PRODUCT}

        root = json.load(urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8402/", headers={"User-Agent": "Mozilla/5.0 healthcheck"}), timeout=20))
        rooted = {e["path"] for e in root["endpoints"]["free"] + root["endpoints"]["paid"]}
        paid_paths = {e["path"] for e in root["endpoints"]["paid"]}

        man = json.load(urllib.request.urlopen(
            "http://127.0.0.1:8402/.well-known/x402", timeout=20))
        # resources are absolute URLs; compare on path only
        from urllib.parse import urlparse
        manifested = {urlparse(r["resource"]).path for r in man.get("resources", [])}

        unadvertised = sorted(real - rooted)
        if unadvertised:
            problems.append(f"ROUTE GAP: {len(unadvertised)} live route(s) absent from root "
                            f"listing — {', '.join(unadvertised[:4])}")
        phantom = sorted(rooted - real)
        if phantom:
            problems.append(f"ROUTE GAP: root advertises {len(phantom)} path(s) that are not "
                            f"routes — {', '.join(phantom[:4])}")
        unmanifested = sorted(paid_paths - manifested)
        if unmanifested:
            problems.append(f"ROUTE GAP: {len(unmanifested)} paid route(s) absent from the x402 "
                            f"manifest — {', '.join(unmanifested[:4])}")
        log(f"  route table: {len(real)} live /api/v1 routes, {len(rooted)} in root, "
            f"{len(manifested)} in manifest — {len(unadvertised)} unadvertised, "
            f"{len(phantom)} phantom, {len(unmanifested)} unmanifested")
    except Exception as e:
        problems.append(f"route-table diff failed: {str(e)[:60]}")

    # PSA population enrichment (launchd com.mememerchants.psa-population, 05:30).
    # Added 2026-07-24: the PSA API began returning 403 on EVERY call that day and
    # nothing noticed — this job had zero observer coverage, so a dead credential
    # would have burned the daily run indefinitely. Alarms only on the auth
    # failure (actionable: renew the token/subscription). Deliberately does NOT
    # alarm on "0 cards enriched": that is a separate, known design weakness —
    # cert numbers are scraped from eBay listing titles and usually absent — and
    # alarming on it would be constant noise until the strategy is reworked.
    try:
        psa_log = os.path.expanduser("~/logs/psa_population.log")
        with open(psa_log, "rb") as f:
            f.seek(max(0, os.path.getsize(psa_log) - 20000))
            tail = f.read().decode("utf-8", "replace")
        today_lines = [l for l in tail.splitlines() if TODAY.isoformat() in l]
        forbidden = sum(1 for l in today_lines if "403" in l)
        log(f"  PSA population: {len(today_lines)} log lines today, {forbidden} auth failure(s)")
        # Alert-fatigue fix (2026-07-26, sailorpepe: "im still getting those psa
        # messages"): this fired EVERY morning since Jul 24 for a known, external,
        # unresolved condition — and its old wording ("token is valid, worked
        # 2026-07-23") aged into nonsense. New policy: while the condition is
        # UNCHANGED, remind on Mondays only; alert IMMEDIATELY the day PSA access
        # comes back. State survives via a tiny JSON file.
        import json as _json
        psa_state_p = os.path.expanduser("~/.cache/psa_alert_state.json")
        try:
            with open(psa_state_p) as f:
                psa_prev = _json.load(f).get("status")
        except Exception:
            psa_prev = None
        # 2026-07-27 (sailorpepe: "its still talking about the psa api"): the
        # Monday throttle was the WRONG fix — it reduced the frequency of noise
        # instead of removing it. Alerts must fire on CHANGE, not on a state we
        # already understand. PSA access is closed to everyone (proven with a
        # brand-new account's fresh token), the slab census replaced it, and
        # there is no action left to take. A recurring page for a permanent,
        # mitigated, external condition just teaches us to ignore the phone —
        # which is expensive the day a real alarm fires. So: LOG it, never page
        # it. The 🎉 restoration branch below still pages immediately, because
        # THAT is a change and it is actionable.
        if forbidden:
            if psa_prev != "revoked":
                problems.append(
                    f"PSA public API now returning 403 ({forbidden}x today). "
                    f"First detection of this state — investigate.")
            else:
                log(f"  PSA population: still closed ({forbidden}x 403) — known, "
                    f"permanent, replaced by the slab census. Not alerting.")
            psa_now = "revoked"
        elif today_lines:
            if psa_prev == "revoked":
                problems.append("🎉 PSA API ACCESS RESTORED — the population job is "
                                "authenticating again. Re-probe the spec endpoints and "
                                "restart the pop-report rework discussion.")
            psa_now = "ok"
        else:
            psa_now = psa_prev  # job didn't run; keep prior state
        try:
            os.makedirs(os.path.dirname(psa_state_p), exist_ok=True)
            with open(psa_state_p, "w") as f:
                _json.dump({"status": psa_now, "as_of": TODAY.isoformat()}, f)
        except Exception:
            pass
    except OSError:
        log("  PSA population: log not found (job may not have run)")

    # Crypto/NFT calibration panel (daily_pipeline step 8, added 2026-07-24).
    # This job's whole value is UNBROKEN daily accumulation: conformal needs >=120
    # assets x >=60 days, and a gap doesn't just lose a row, it pushes the earliest
    # possible calibration date back. A silent stall here would cost months before
    # anyone noticed, which is exactly the failure mode we keep finding. So we alarm
    # on staleness (>1 day since the newest row), not on row counts.
    try:
        con = ro(os.path.expanduser(
            "~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite"))
        row = con.execute("SELECT MAX(date) FROM crypto_price_history").fetchone()
        newest = row[0] if row else None
        if not newest:
            problems.append("crypto/NFT panel: table empty — the daily logger has never "
                            "successfully run (blocks NFT/crypto conformal entirely).")
        else:
            age = days_old(newest)
            stats = con.execute(
                "SELECT kind, COUNT(DISTINCT asset_id), COUNT(DISTINCT date) "
                "FROM crypto_price_history GROUP BY kind").fetchall()
            desc = ", ".join(f"{k}: {a} assets x {d}d" for k, a, d in stats)
            log(f"  crypto/NFT panel: newest {newest} ({age}d old) — {desc}")
            if age is not None and age > 1:
                problems.append(
                    f"crypto/NFT panel STALE: newest row {newest} ({age}d old). Every "
                    f"missed day delays NFT/crypto conformal by a day. Check "
                    f"~/logs/crypto_logger.log and daily_pipeline step 8.")
        con.close()
    except Exception as e:
        log(f"  crypto/NFT panel: check skipped ({str(e)[:60]})")

    # Observed slab census (daily_pipeline step 9, added 2026-07-25). Same
    # staleness logic as the crypto panel: the census is a supply TIME SERIES,
    # so a silent stall costs history that cannot be backfilled. eBay throttling
    # or a key problem would surface here as staleness.
    try:
        con = ro(os.path.expanduser(
            "~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite"))
        row = con.execute("SELECT MAX(last_seen), COUNT(*), COUNT(DISTINCT cert_number),"
                          " COUNT(DISTINCT product_id) FROM slab_census").fetchone()
        newest, slabs, certs, cards = row if row else (None, 0, 0, 0)
        if not newest:
            log("  slab census: table empty (first pipeline run pending)")
        else:
            age = days_old(newest)
            log(f"  slab census: newest {newest} ({age}d old) — {slabs} slabs, "
                f"{certs} certs, {cards} cards")
            if age is not None and age > 1:
                problems.append(
                    f"slab census STALE: newest sighting {newest} ({age}d old) — "
                    f"supply history can't be backfilled. Check ~/logs/slab_census.log "
                    f"and daily_pipeline step 9 (eBay 429s would show there).")
        con.close()
    except Exception as e:
        log(f"  slab census: check skipped ({str(e)[:60]})")

    # Soul grade print (soul_predictions.py --score, 05:10 daily). Added
    # 2026-07-25 ahead of the FIRST maturity date 2026-07-31: 819 predictions
    # mature that day and sailorpepe's LitVM follow-up cites the live numbers
    # the same morning — a silent scoring failure collapses the send plan.
    # This check runs at 07:00, after the 05:10 scorer.
    # Dry-run baseline (clock-shifted, 2026-07-25): 774/819 score, 45 skip on
    # missing prices (retry daily), ~81% hit rate ex-push, ~37% pushes.
    try:
        sdb = ro(os.path.expanduser(
            "~/Documents/undesirables-x402-server/soul_predictions.sqlite"))
        t = TODAY.isoformat()
        due = sdb.execute("SELECT COUNT(*) FROM soul_predictions WHERE matures_on<=?",
                          (t,)).fetchone()[0]
        done = sdb.execute("SELECT COUNT(*) FROM soul_predictions WHERE scored=1").fetchone()[0]
        backlog = sdb.execute("SELECT COUNT(*) FROM soul_predictions "
                              "WHERE scored=0 AND matures_on<=?", (t,)).fetchone()[0]
        sdb.close()
        if due:
            log(f"  soul grade print: {done} scored, {backlog} due-unscored (of {due} due)")
            if done == 0:
                problems.append(
                    f"SOUL GRADE PRINT FAILED: {due} predictions matured but ZERO are "
                    f"scored — the 05:10 soul_predictions.py --score run did not do its "
                    f"job. The July-31 send plan cites these numbers. Check "
                    f"~/logs/soul_predictions.log NOW.")
            elif backlog > 80:   # ~10% of a weekly cohort — skip backlog is growing
                problems.append(
                    f"soul grade print: {backlog} matured predictions still unscored "
                    f"(missing prices don't retry forever if products stay unpriced). "
                    f"Dry-run baseline was 45 — investigate before it compounds.")
        else:
            log("  soul grade print: nothing matured yet (first cohort 2026-07-31)")
    except Exception as e:
        log(f"  soul grade print: check skipped ({str(e)[:60]})")

    # Sports player-stat panel (daily_pipeline step 10, added 2026-07-27).
    # Same logic as the crypto panel: the value is UNBROKEN accumulation, and a
    # missed day is a day of season history that cannot be backfilled — MLB
    # serves CURRENT season totals, not a historical daily series. Alarms on
    # staleness only. In-season MLB runs Apr-Oct; off-season silence is normal
    # and must not page, hence the >2 day threshold and the empty-table pass.
    try:
        con = ro(os.path.expanduser(
            "~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite"))
        row = con.execute("SELECT MAX(date) FROM player_stats_history").fetchone()
        newest = row[0] if row else None
        if not newest:
            log("  sports panel: table empty (first pipeline run pending)")
        else:
            age = days_old(newest)
            stats = con.execute(
                "SELECT league, COUNT(DISTINCT player_id), COUNT(DISTINCT date) "
                "FROM player_stats_history GROUP BY league").fetchall()
            desc = ", ".join(f"{lg}: {p} players x {d}d" for lg, p, d in stats)
            log(f"  sports panel: newest {newest} ({age}d old) — {desc}")
            if age is not None and age > 2:
                problems.append(
                    f"sports stat panel STALE: newest {newest} ({age}d old). Season "
                    f"history can't be backfilled — MLB serves current totals only. "
                    f"Check ~/logs/sports_stats.log and daily_pipeline step 10.")
        con.close()
    except Exception as e:
        log(f"  sports panel: check skipped ({str(e)[:60]})")

    # Sports Merkle commit lag (SportsStatsRegistry, chain 4441, added 2026-07-27).
    # The failure this catches is SILENT and PERMANENT: step 10 keeps logging
    # rows while step 11 quietly fails, so we accumulate stat history that was
    # never committed. Those days can never be made provable after the fact --
    # the contract is write-once and backdating is exactly what it prevents.
    # Rows-without-a-root is therefore an alarm, not a warning.
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        from web3 import Web3 as _W3
        _eday = lambda s: int(_dt.strptime(s, "%Y-%m-%d")
                              .replace(tzinfo=_tz.utc).timestamp() // 86400)
        con = ro(os.path.expanduser(
            "~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite"))
        days = con.execute(
            "SELECT league, date, COUNT(DISTINCT player_id) FROM player_stats_history "
            "GROUP BY league, date ORDER BY date DESC LIMIT 14").fetchall()
        con.close()

        # BOTH legs are checked. Base is the durability leg (a testnet reset would
        # erase LiteForge entirely), so a Base gap is the one that actually costs
        # us the claim -- but a silent LiteForge gap would quietly hollow out the
        # LitVM story, so neither is allowed to fail unwatched.
        _alchemy = env("ALCHEMY_API_KEY")
        for _name, _file, _rpc in (
            ("base", "sports_deployment_base.json",
             f"https://base-mainnet.g.alchemy.com/v2/{_alchemy}"),
            ("liteforge", "sports_deployment_v2.json",
             "https://liteforge.rpc.caldera.xyz/http"),
        ):
            try:
                dep = _json.load(open(os.path.expanduser(
                    f"~/Documents/undesirables-x402-server/{_file}")))
                _w = _W3(_W3.HTTPProvider(_rpc))
                _c = _w.eth.contract(
                    address=_W3.to_checksum_address(dep["contract"]), abi=dep["abi"])
                today_ed = _c.functions.currentEpochDay().call()
                total = _c.functions.totalCommits().call()
                log(f"  sports merkle [{_name}]: {total} day(s) on chain "
                    f"{dep['chain_id']} ({dep['contract'][:10]}…)")

                # V2 refuses any commit older than MAX_COMMIT_LAG_DAYS, so an
                # uncommitted day is on a HARD DEADLINE — once it ages out it is
                # unprovable forever and no fix recovers it. Split accordingly.
                urgent, lost = [], []
                for lg, d, n in days:
                    if n < 25:
                        continue
                    ed = _eday(d)
                    if _c.functions.hasSnapshot(lg, ed).call():
                        continue
                    (lost if today_ed - ed > 3 else urgent).append(
                        (lg, d, n, today_ed - ed))
                if urgent:
                    ws = ", ".join(f"{lg} {d} ({n}p, {3 - age}d left)"
                                   for lg, d, n, age in urgent[:4])
                    problems.append(
                        f"[{_name}] sports days logged but NOT committed — ON "
                        f"DEADLINE: {ws}. Commits older than 3 days are refused, "
                        f"so re-run sports_merkle_updater.py NOW or these are "
                        f"unprovable forever. See ~/logs/sports_merkle.log")
                if lost:
                    ws = ", ".join(f"{lg} {d}" for lg, d, _, _ in lost[:4])
                    problems.append(
                        f"[{_name}] sports days PERMANENTLY uncommitted (past the "
                        f"3-day window): {ws}. Cannot be recovered — backdating is "
                        f"refused by design. Record the gap; do not widen it.")
            except Exception as e:
                problems.append(
                    f"sports merkle [{_name}] CHECK FAILED: {str(e)[:70]} — the "
                    f"commit deadline is unmonitored on this chain right now")

        # Base gas runway. Commits are ~$0.004 each, so this never costs real
        # money — but an empty wallet silently converts every future day into a
        # permanent gap, which is the expensive part.
        try:
            _w = _W3(_W3.HTTPProvider(
                f"https://base-mainnet.g.alchemy.com/v2/{_alchemy}"))
            dep = _json.load(open(os.path.expanduser(
                "~/Documents/undesirables-x402-server/sports_deployment_base.json")))
            bal = _w.eth.get_balance(_W3.to_checksum_address(dep["deployer"]))
            per = 175_000 * _w.eth.gas_price
            runway = bal // per if per else 0
            # Report DAYS, not commits. We commit once per league per night, so
            # a "20 commits left" reading is really 5 days once four leagues are
            # active — the raw count reads far safer than it is.
            con2 = ro(os.path.expanduser(
                "~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite"))
            n_leagues = con2.execute(
                "SELECT COUNT(DISTINCT league) FROM player_stats_history "
                "WHERE date=(SELECT MAX(date) FROM player_stats_history)"
            ).fetchone()[0] or 1
            con2.close()
            days_left = runway // n_leagues
            log(f"  base gas runway: {_w.from_wei(bal, 'ether'):.6f} ETH "
                f"≈ {runway} commits ≈ {days_left}d at {n_leagues} league(s)/night")
            if days_left < 21:
                problems.append(
                    f"Base commit wallet low: ~{days_left} DAYS left "
                    f"({runway} commits at {n_leagues} leagues/night, "
                    f"{_w.from_wei(bal, 'ether'):.6f} ETH). Top up "
                    f"{dep['deployer']} — an empty wallet turns every future day "
                    f"into a permanently unprovable gap.")
        except Exception as e:
            log(f"  base gas runway: check skipped ({str(e)[:50]})")
    except Exception as e:
        log(f"  sports merkle: check skipped ({str(e)[:60]})")

    # Forecast board commitments (PredictionRegistry, Base 8453, added 2026-07-27).
    # This is the SHORTEST deadline in the stack: the contract accepts a board's
    # root only while today < issue_day + 7 (its shortest horizon), because after
    # that the board has begun resolving and a "prediction" committed then proves
    # nothing. Seven days is the entire recovery budget, and it is not extendable
    # — the whole value of the published hit rate rests on that refusal.
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        from web3 import Web3 as _W3
        dep = _json.load(open(os.path.expanduser(
            "~/Documents/undesirables-x402-server/prediction_deployment_base.json")))
        _w = _W3(_W3.HTTPProvider(
            f"https://base-mainnet.g.alchemy.com/v2/{env('ALCHEMY_API_KEY')}"))
        _c = _w.eth.contract(address=_W3.to_checksum_address(dep["contract"]),
                             abi=dep["abi"])
        _eday = lambda s: int(_dt.strptime(s, "%Y-%m-%d")
                              .replace(tzinfo=_tz.utc).timestamp() // 86400)
        min_h = _c.functions.streams("tcg_forecast").call()[1]
        today_ed = _c.functions.currentEpochDay().call()
        fl = ro(os.path.expanduser(
            "~/Documents/undesirables-x402-server/forecast_ledger.sqlite"))
        dates = [r[0] for r in fl.execute(
            "SELECT DISTINCT forecast_date FROM forecast_ledger "
            "ORDER BY forecast_date DESC LIMIT 12")]
        fl.close()
        log(f"  forecast commitments: {_c.functions.totalForecasts().call()} "
            f"board(s) on Base ({dep['contract'][:10]}…)")
        urgent = []
        for d in dates:
            ed = _eday(d)
            if today_ed >= ed + min_h:
                continue                      # already past saving; not actionable
            if not _c.functions.hasForecast("tcg_forecast", ed).call():
                urgent.append(f"{d} ({ed + min_h - today_ed}d left)")
        if urgent:
            problems.append(
                f"forecast board(s) NOT committed on-chain: {', '.join(urgent[:5])}. "
                f"After the window the board has begun resolving and can never be "
                f"committed — our published hit rate becomes unverifiable for those "
                f"days. Run: cd ~/Documents/undesirables-x402-server && "
                f"./venv/bin/python forecast_commit.py --backfill")
    except Exception as e:
        problems.append(
            f"forecast commitment check FAILED: {str(e)[:70]} — the shortest "
            f"deadline in the stack is currently unmonitored")

    # CLAIMS REGISTER (added 2026-07-28). Every publishable number must be
    # regeneratable from source, with its universe/window/n attached. A claim
    # that can no longer be derived is a claim we cannot defend — it should come
    # off the site rather than sit there because it was true once. This runs the
    # register in --check mode; a non-zero exit means something we publish has
    # lost its provenance.
    try:
        import subprocess as _sp
        _r = _sp.run(
            [os.path.expanduser("~/Documents/undesirables-x402-server/venv/bin/python"),
             os.path.expanduser("~/Documents/undesirables-x402-server/claims_register.py"),
             "--check"], capture_output=True, text=True, timeout=900)
        _tail = [l for l in _r.stdout.splitlines() if "derivable" in l]
        log(f"  claims register: {_tail[-1] if _tail else 'no summary line'}")
        if _r.returncode != 0:
            _bad = [l.strip() for l in _r.stdout.splitlines() if "UNDERIVABLE" in l]
            problems.append(
                f"claims register has UNDERIVABLE entries: {'; '.join(_bad[:3])}. "
                f"A number we cannot regenerate from source cannot be defended — "
                f"pull it from public copy until it can.")
    except Exception as e:
        problems.append(f"claims register FAILED to run: {str(e)[:70]}")

    # Realised-price commitments (stream tcg_price, added 2026-07-28).
    # This is the OTHER half of every accuracy claim. Forecast roots were already
    # committed; without the realised panel a third party can verify what we
    # PREDICTED but must take our word for what HAPPENED — which is the half that
    # matters when the number flatters us. Same 3-day write-once window as the
    # rest, so an uncommitted day ages out permanently and the loop stays open
    # for that date forever.
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        from web3 import Web3 as _W3
        dep = _json.load(open(os.path.expanduser(
            "~/Documents/undesirables-x402-server/sports_deployment_base.json")))
        _w = _W3(_W3.HTTPProvider(
            f"https://base-mainnet.g.alchemy.com/v2/{env('ALCHEMY_API_KEY')}"))
        _c = _w.eth.contract(address=_W3.to_checksum_address(dep["contract"]),
                             abi=dep["abi"])
        _eday = lambda s: int(_dt.strptime(s, "%Y-%m-%d")
                              .replace(tzinfo=_tz.utc).timestamp() // 86400)
        today_ed = _c.functions.currentEpochDay().call()
        con = ro(os.path.expanduser(
            "~/Documents/undesirables-mcp-server/.cache/market_memory.sqlite"))
        days = [r[0] for r in con.execute(
            "SELECT DISTINCT date FROM price_history WHERE product_id<9500000 "
            "ORDER BY date DESC LIMIT 5")]
        con.close()
        urgent = []
        for d in days:
            ed = _eday(d)
            if today_ed - ed > 3:
                continue                     # already past saving
            if not _c.functions.hasSnapshot("tcg_price", ed).call():
                urgent.append(f"{d} ({3 - (today_ed - ed)}d left)")
        log(f"  price commitments: checked {len(days)} recent day(s) on "
            f"tcg_price stream")
        if urgent:
            problems.append(
                f"realised PRICE panel not committed: {', '.join(urgent)}. Past "
                f"the 3-day window it can never be committed, and every accuracy "
                f"claim covering that date becomes unverifiable by anyone but us. "
                f"Run: cd ~/Documents/undesirables-x402-server && "
                f"./venv/bin/python tcg_price_commit.py --backfill")
    except Exception as e:
        problems.append(f"price-commitment check FAILED: {str(e)[:70]}")

    # CONTRACT OWNERSHIP WATCH (added 2026-07-28, sailorpepe-approved).
    # One key is currently owner AND publisher on every registry, and it lives
    # hot in .env on this machine. A leak is unrecoverable: write-once means the
    # attacker's junk roots for future days can never be replaced, and
    # transferOwnership would take the contracts outright. sailorpepe deferred
    # the cold-wallet split to ~2026-08-04, so this covers the gap — it cannot
    # PREVENT a takeover, but it turns "found out weeks later when a commit
    # silently stopped working" into "knew within a day".
    #
    # DESIGN RULE: a missing or unreadable baseline is an ALARM, never a silent
    # re-baseline. Auto-healing here would mean an attacker who changed owner
    # AND deleted the file gets a clean bill of health — the exact failure this
    # check exists to prevent.
    try:
        import json as _json
        from web3 import Web3 as _W3
        _basep = os.path.expanduser("~/.cache/undesirables_contract_owners.json")
        if not os.path.exists(_basep):
            problems.append(
                f"contract-ownership baseline MISSING ({_basep}). Not re-created "
                f"automatically on purpose — verify owner/publisher by hand "
                f"against the tracker before restoring it.")
        else:
            _b = _json.load(open(_basep))
            _al = env("ALCHEMY_API_KEY")
            _rpcs = {
                "base": f"https://base-mainnet.g.alchemy.com/v2/{_al}",
                "liteforge": "https://liteforge.rpc.caldera.xyz/http",
            }
            _OWNER_ABI = [
                {"name": "owner", "type": "function", "stateMutability": "view",
                 "inputs": [], "outputs": [{"type": "address"}]},
                {"name": "publisher", "type": "function", "stateMutability": "view",
                 "inputs": [], "outputs": [{"type": "address"}]},
            ]
            _drift, _checked = [], 0
            for _name, _exp in (_b.get("contracts") or {}).items():
                try:
                    _w = _W3(_W3.HTTPProvider(_rpcs[_exp["rpc_kind"]]))
                    _c = _w.eth.contract(
                        address=_W3.to_checksum_address(_exp["contract"]),
                        abi=_OWNER_ABI)
                    _now_o = _c.functions.owner().call()
                    _checked += 1
                    if _now_o != _exp["owner"]:
                        _drift.append(f"{_name} OWNER {_exp['owner'][:10]}… → "
                                      f"{_now_o[:10]}…")
                    # publisher() is optional per-entry: MerklePriceOracle (added
                    # 2026-07-31) is Ownable2Step with no owner/publisher split.
                    if "publisher" in _exp:
                        _now_p = _c.functions.publisher().call()
                        if _now_p != _exp["publisher"]:
                            _drift.append(f"{_name} PUBLISHER {_exp['publisher'][:10]}… → "
                                          f"{_now_p[:10]}…")
                except Exception as e:
                    # An unreachable chain is not drift — say so rather than
                    # implying a takeover, but do not count it as verified.
                    log(f"  ownership watch: {_name} unreadable ({str(e)[:50]})")
            log(f"  contract ownership: {_checked}/{len(_b.get('contracts') or {})} "
                f"verified unchanged")
            if _drift:
                problems.append(
                    "🚨 CONTRACT OWNERSHIP CHANGED — " + "; ".join(_drift) +
                    ". If this was not you, the signing key is compromised: every "
                    "future day can be permanently poisoned and the contracts may "
                    "already be lost. If it WAS you (cold-wallet split), update "
                    "~/.cache/undesirables_contract_owners.json to the new values.")
    except Exception as e:
        problems.append(f"contract-ownership watch FAILED: {str(e)[:70]} — "
                        f"takeover would currently go unnoticed")

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
                    timeout=15) if not NO_PAGE else None
                log("  (phone alert SUPPRESSED — NO_PAGE=1)" if NO_PAGE
                    else "  (phone alert sent)")
            except Exception as e:
                log(f"  (ntfy failed: {e})")
    else:
        log("✅ ALL GREEN — every data stream fresh, invariants hold, roots committed, oracle up.")


if __name__ == "__main__":
    main()
