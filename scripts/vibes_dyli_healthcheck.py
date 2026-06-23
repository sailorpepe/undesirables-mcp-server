#!/usr/bin/env python3
"""
vibes_dyli_healthcheck.py — pings if the DYLI Vibes feed goes dark.

DYLI's /api/explore is an undocumented endpoint; if its shape changes or it goes
down, vibes_dyli_ingest.py just logs an error and leaves existing data untouched —
so a silent stall is possible. This checks two things daily (run after the 4am
ingest):
  1. FRESHNESS — days since the last successful DYLI snapshot in vibes_price_history.
  2. REACHABILITY — can we still pull Vibes products from /api/explore right now.
If the feed is stale >= STALE_DAYS or unreachable, it ALERTS:
  - writes ~/logs/DYLI_FEED_DOWN.flag (+ loud log line), and
  - if NTFY_TOPIC is set (in the x402 .env), pushes to https://ntfy.sh/<topic> so you
    get a phone notification (install the free ntfy app, subscribe to that topic).
When healthy it clears the flag. Read-only on the DB; stdlib only.
"""
import os, re, json, sqlite3, urllib.request
from datetime import date, datetime, timezone

MCP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(MCP, ".cache", "market_memory.sqlite")
X402_ENV = os.path.expanduser("~/Documents/undesirables-x402-server/.env")
FLAG = os.path.expanduser("~/logs/DYLI_FEED_DOWN.flag")
LOG = os.path.expanduser("~/logs/vibes_dyli_health.log")
EXPLORE = "https://www.dyli.io/api/explore?page=1&limit=50"
STALE_DAYS = 2


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def env(k):
    if os.environ.get(k):
        return os.environ[k]
    if os.path.exists(X402_ENV):
        for line in open(X402_ENV):
            m = re.match(rf"^{k}=(.*)$", line.strip())
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return None


def notify(title, body):
    topic = env("NTFY_TOPIC")
    if not topic:
        log("(no NTFY_TOPIC set — phone push skipped; add NTFY_TOPIC=... to the x402 .env + "
            "subscribe to it in the ntfy app)")
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}", data=body.encode(),
            headers={"Title": title, "Priority": "high", "Tags": "warning"})
        urllib.request.urlopen(req, timeout=15)
        log(f"pushed ntfy alert to topic '{topic}'")
    except Exception as e:
        log(f"ntfy push failed: {e}")


def main():
    today = date.today()
    problems = []

    # 1) freshness
    last = None
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        last = c.execute("SELECT MAX(date) FROM vibes_price_history WHERE source='dyli'").fetchone()[0]
        c.close()
    except Exception as e:
        problems.append(f"DB read error: {e}")
    if last:
        age = (today - date.fromisoformat(last)).days
        if age >= STALE_DAYS:
            problems.append(f"no fresh DYLI snapshot for {age}d (last {last})")
    else:
        problems.append("no DYLI snapshots in vibes_price_history at all")

    # 2) reachability
    try:
        req = urllib.request.Request(EXPLORE, headers={"User-Agent": "UndesirablesOracle/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=20))
        nv = sum(1 for p in d.get("products", []) if str(p.get("brand", "")).lower() == "vibes")
        if nv == 0:
            problems.append("DYLI reachable but 0 Vibes on page 1 (catalog moved? schema changed?)")
    except Exception as e:
        problems.append(f"DYLI /api/explore unreachable: {e}")

    if problems:
        body = "DYLI Vibes feed problem:\n- " + "\n- ".join(problems)
        json.dump({"down_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "problems": problems, "last_snapshot": last}, open(FLAG, "w"), indent=2)
        log("🚨 DYLI FEED DOWN: " + " | ".join(problems))
        notify("🚨 DYLI Vibes feed down", body)
    else:
        if os.path.exists(FLAG):
            os.remove(FLAG)
            log("DYLI feed recovered — cleared flag")
        log(f"ok — last snapshot {last}, DYLI reachable")


if __name__ == "__main__":
    main()
