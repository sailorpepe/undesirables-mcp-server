# VENDORED from the Studio's technocore-census repo (all tests pass 2026-08-26).
# DO NOT MODIFY THE SAFETY LOGIC — the allowlist/write-refusal is the reviewed,
# test-proven surface. Only the READ client is vendored; census methodology,
# DID tooling, and the write-capable publish module deliberately stay out of
# this public-facing package.
# Upstream: sailorpepe/technocore-census tccensus/client.py @ f4e8f25.
"""Read-only HTTP client for technocore.chat.

Safety model
------------
This client is *structurally* incapable of writing to the server. Every
request is routed through :meth:`ReadOnlyClient.get`, which:

  * refuses any method other than GET,
  * rejects any path that is not on the read allowlist, and
  * rejects any path containing a write verb (``/say``, ``/set``,
    ``/say-signed``) regardless of the allowlist.

There is no code path in this module that issues a POST or a write GET.
The crawler cannot post a message, set a note, register a DID, or spend a
nonce. It only observes.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_BASE = "https://technocore.chat"

# Deliberately anonymous. Do NOT put a handle, email, repo URL or any other
# identifier in here: every request carries it to the server, which would tie
# the crawl to an identity before we have decided whether to publish at all.
# Override via TC_CENSUS_UA only when we have chosen to be attributable.
USER_AGENT = os.environ.get("TC_CENSUS_UA", "technocore-census/0.1 (read-only)")

# Write verbs that must never appear in any path we fetch. A path containing
# any of these is a write, no matter what else it looks like.
_FORBIDDEN_SEGMENTS = ("/say", "/set", "/say-signed", "/delete", "/claim/")

# Read endpoints we are willing to touch. Matched against the path prefix.
_ALLOWED_PREFIXES = (
    "/rooms",
    "/r/",              # room reads: /r/<room>, /r/<room>?since=..., /r/events
    "/kv/",             # note reads: /kv/<ns>, /kv/<ns>/<key>
    "/.well-known/",
    "/config",
    "/openapi.json",
    "/llms.txt",
    "/skill.md",
    "/patterns.md",
    "/interop.md",
    "/auth.md",
)


class WriteAttemptError(RuntimeError):
    """Raised if any code tries to make this client perform a write."""


# The only host this tool is ever allowed to contact. A census that can be
# pointed at an arbitrary host is an exfiltration primitive.
_ALLOWED_HOSTS = ("technocore.chat", "www.technocore.chat")


def _split_url(url: str) -> tuple[str, str]:
    """Return (host, path) with the query stripped from the path."""
    after_scheme = url.split("://", 1)[-1]
    slash = after_scheme.find("/")
    if slash == -1:
        return after_scheme.split("?", 1)[0].lower(), "/"
    host = after_scheme[:slash].lower()
    path = after_scheme[slash:].split("?", 1)[0]
    # Drop any userinfo@ and :port so "evil.com@technocore.chat" can't sneak by.
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0]
    return host, path


def assert_read_only(url: str) -> None:
    """Raise unless ``url`` is a pure read of technocore.chat.

    Public so tests can call it.
    """
    host, path = _split_url(url)
    if host not in _ALLOWED_HOSTS:
        raise WriteAttemptError(f"refusing non-technocore host: {host!r}")
    low = path.lower()
    for seg in _FORBIDDEN_SEGMENTS:
        if seg in low:
            raise WriteAttemptError(f"refusing write-shaped path: {path!r}")
    if not any(path == p or path.startswith(p) for p in _ALLOWED_PREFIXES):
        raise WriteAttemptError(f"path not on read allowlist: {path!r}")


@dataclass
class Limits:
    reads_per_minute_per_ip: float = 60.0  # conservative default; refined from agent.json

    @property
    def min_interval(self) -> float:
        return 60.0 / max(self.reads_per_minute_per_ip, 1.0)


@dataclass
class ReadOnlyClient:
    base: str = DEFAULT_BASE
    timeout: float = 30.0
    limits: Limits = field(default_factory=Limits)
    _last_request_at: float = 0.0
    request_count: int = 0

    def _throttle(self) -> None:
        # Simple client-side spacing so we stay under the read bucket even
        # before the server tells us to slow down.
        wait = self.limits.min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str, *, retries: int = 3) -> tuple[int, str]:
        """GET a read-only path. Returns (status, body_text)."""
        url = path if path.startswith("http") else self.base + path
        assert_read_only(url)  # hard gate — no write can slip through here

        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            req = urllib.request.Request(
                url, method="GET", headers={"User-Agent": USER_AGENT}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self._last_request_at = time.monotonic()
                    self.request_count += 1
                    return resp.status, resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                self._last_request_at = time.monotonic()
                self.request_count += 1
                if e.code == 429 and attempt <= retries:
                    retry_after = e.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2.0 * attempt
                    time.sleep(delay)
                    continue
                return e.code, (e.read().decode("utf-8", "replace") if e.fp else "")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt <= retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise RuntimeError(f"GET {url} failed after {retries} retries: {e}")

    def get_json(self, path: str, **kw):
        status, body = self.get(path, **kw)
        if status != 200:
            return status, None
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, None

    def refine_limits_from_well_known(self) -> None:
        """Ask the server what its read budget is and slow down to match."""
        _, doc = self.get_json("/.well-known/agent.json")
        if not isinstance(doc, dict):
            return
        lim = doc.get("limits") or {}
        rpm = lim.get("reads_per_minute_per_ip")
        if isinstance(rpm, (int, float)) and rpm > 0:
            # Use 75% of the stated budget as our ceiling — leave headroom.
            self.limits.reads_per_minute_per_ip = float(rpm) * 0.75
