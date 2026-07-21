#!/usr/bin/env python3
"""
TCG Oracle — Remote MCP Server (Streamable HTTP)
================================================
Public endpoint: https://mcp.the-undesirables.com/mcp
Lightweight remote wrapper that exposes the top TCG Oracle tools over
HTTPS + SSE transport for remote MCP clients:

  - Perplexity AI (Connectors → Custom Remote)
  - Cursor IDE
  - Claude Desktop
  - VS Code + Copilot
  - Windsurf
  - CrewAI / LangGraph / any MCP-compatible agent

This is a PROXY — it calls into the x402 server's internal MCP bridge
or directly into the tool functions, then returns results over SSE.

Usage:
    python mcp_remote.py                       # Streamable HTTP on port 8443
    python mcp_remote.py --port 9000           # Custom port
    python mcp_remote.py --transport sse       # Legacy SSE (deprecated transport)

Client setup (one URL, no install):
    Claude Desktop / Cursor / Windsurf / VS Code:
        add an MCP server with URL https://mcp.the-undesirables.com/mcp
    Perplexity:
        Settings → Connectors → + Custom Connector → Remote
        URL: https://mcp.the-undesirables.com/mcp
    Auth: none. Free tools answer immediately; paid tools return an x402
    402 with payment details, so an agent with a funded wallet can settle
    and retry without any signup.
"""

import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
X402_BASE = os.getenv("X402_BASE_URL", "https://oracle.the-undesirables.com")
PORT = int(os.getenv("MCP_REMOTE_PORT", "8443"))
TRANSPORT = os.getenv("MCP_REMOTE_TRANSPORT", "streamable-http")

PUBLIC_HOST = os.getenv("MCP_PUBLIC_HOST", "mcp.the-undesirables.com")

mcp = FastMCP(
    "TCG Oracle",
    instructions=(
        "Financial intelligence API for the $50B+ trading card market. "
        "Search 446K+ products across 25+ games, grade card images with AI, "
        "forecast prices with a conformal-calibrated risk model (Monte Carlo opt-in), and get ROI verdicts "
        "on whether to send cards for professional grading. "
        "All data comes from TCGCSV daily market snapshots and real-time analysis."
    ),
)

# DNS-rebinding protection stays ON; we just allowlist the public hostname.
# Without this the MCP SDK rejects every tunnelled request with a bare
# "Invalid Host header" (surfacing as HTTP 421 at the Cloudflare edge) because
# allowed_hosts defaults to localhost only — caught on the 2026-07-21 deploy,
# and invisible to any localhost test. MCP_PUBLIC_HOST overrides for other
# deployments.
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[PUBLIC_HOST, f"{PUBLIC_HOST}:*",
                   "127.0.0.1:*", "localhost:*", "[::1]:*"],
    allowed_origins=[f"https://{PUBLIC_HOST}", f"https://{PUBLIC_HOST}:*",
                     "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
)


# ---------------------------------------------------------------------------
# Helper: Call x402 server endpoints
# ---------------------------------------------------------------------------
# The oracle's graceful-402 handler treats any "httpx"/"x402" User-Agent as an
# SDK client and returns the RAW 402 — empty body, payment details only in the
# header. httpx's default UA therefore made every paid tool surface a useless
# `HTTP 402: {}` (caught on the 2026-07-21 deploy gate). We send our own UA so
# we get the enriched guidance body, AND decode the payment-required envelope,
# so an agent receives both a readable explanation and the machine-readable
# accepts[] it needs to settle and retry. No signup, no auth — that's the pitch.
_UA = {"User-Agent": "undesirables-mcp-remote/1.0"}


def _decode_payment_required(resp) -> dict:
    import base64
    hdr = resp.headers.get("payment-required")
    if not hdr:
        return {}
    try:
        return json.loads(base64.b64decode(hdr + "=" * (-len(hdr) % 4)))
    except Exception:
        return {}


def _call_x402(path: str, params: dict = None, method: str = "GET") -> dict:
    """Call the oracle. Free endpoints answer directly; paid endpoints return a
    structured payment_required payload the caller can act on."""
    try:
        url = f"{X402_BASE}{path}"
        with httpx.Client(timeout=30.0, headers=_UA) as client:
            if method == "POST":
                r = client.post(url, json=params or {})
            else:
                r = client.get(url, params=params or {})
            if r.status_code == 402:
                env = _decode_payment_required(r)
                try:
                    guidance = r.json()
                except Exception:
                    guidance = {}
                acc = (env.get("accepts") or [{}])[0]
                return {
                    "status": "payment_required",
                    "tool": guidance.get("tool"),
                    "price": guidance.get("price"),
                    "network": acc.get("network") or guidance.get("network"),
                    "asset": guidance.get("asset"),
                    "pay_to": acc.get("payTo") or guidance.get("payment_address"),
                    "amount": acc.get("amount"),
                    "how_to_pay": guidance.get("how_to_pay"),
                    "free_preview": guidance.get("free_preview"),
                    "x402": {k: env[k] for k in ("x402Version", "accepts", "resource") if k in env},
                    "note": ("This tool is pay-per-call over x402. Settle the payment above "
                             "with a funded wallet, then call again with the payment proof. "
                             "No account or API key is required."),
                }
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# [TCG] Search — FREE
# ---------------------------------------------------------------------------
@mcp.tool()
def search_tcg_products(
    query: str,
    game: str = "",
    limit: int = 10,
) -> dict:
    """
    Search 446K+ TCG products across 25+ card games.
    Returns card names and IDs, plus current market prices.
    FREE — no payment required.

    Use this when: a user asks about a specific card, wants to find cards,
    or needs current pricing for any trading card game product.

    HOW TO SEARCH (card name AND set name are both searchable):
      • Card name alone casts the widest net: "Charizard", "Black Lotus".
      • Add the SET to pin down a printing: "Base Set Charizard" returns the
        Base Set, Base Set 2 and Shadowless Charizards as separate entries.
        This matters — printings of the "same" card differ wildly in value.
      • Every result carries a "set" field. Use it to choose, then pass that
        result's product_id to the other tools (card_forecast, grade_or_not,
        simulate_price) — exact, and avoids re-searching.
      • Do NOT include rarity or condition words: "Holo", "1st Edition",
        "Shadowless", "PSA 10" are not indexed and will sink an otherwise-good
        query. "Base Set Charizard Holo" → drop "Holo".
      • Got nothing? Remove the rarity words first, then fall back to the plain
        card name.
    """
    params = {"query": query, "limit": min(limit, 50)}
    if game:
        params["game"] = game
    return _call_x402("/api/v1/search", params)


# ---------------------------------------------------------------------------
# [TCG] Market Snapshot — FREE
# ---------------------------------------------------------------------------
@mcp.tool()
def market_snapshot(game: str = "") -> dict:
    """
    Daily TCG market snapshot with top movers, biggest gainers/losers,
    and volume leaders across all 13 supported card games.
    FREE — no payment required.

    Use this when: a user asks "what's trending in the card market?" or
    "what cards are going up/down in value?"
    """
    params = {}
    if game:
        params["game"] = game
    return _call_x402("/api/v1/market", params)


# ---------------------------------------------------------------------------
# [TCG] AI Card Grading — $0.10
# ---------------------------------------------------------------------------
@mcp.tool()
def grade_card(
    image_url: str,
    game: str = "Pokemon",
) -> dict:
    """
    AI-grade a trading card image using a 3-stage pipeline:
    (1) Qwen Vision LLM analyzes corners, edges, surface defects
    (2) OpenCV measures exact centering ratios programmatically
    (3) BGS professional capping algorithm adjusts the final grade

    Returns PSA/Beckett-calibrated subgrades and an overall condition score.
    Also includes a free ROI verdict (should you grade this card?).

    PAID: $0.10 USDC per call (x402 payment on Base network).

    Use this when: a user has a card image and wants to know what grade
    it would receive from PSA or Beckett.
    """
    return _call_x402("/api/v1/grade", {"image_url": image_url, "game": game})


# ---------------------------------------------------------------------------
# [TCG] Grade-or-Not ROI Engine — $0.10
# ---------------------------------------------------------------------------
@mcp.tool()
def grade_or_not(
    card_name: str,
    raw_price: float = 0.0,
    predicted_grade: float = 0.0,
    service_tier: str = "regular",
) -> dict:
    """
    Answers: "Should I grade this card? Will I make money?"

    Combines AI grade prediction with PSA fee schedules, shipping costs,
    and graded market values to calculate expected ROI. Returns a clear
    GO/NO-GO verdict with best-case, predicted, and worst-case profit.

    PAID: $0.10 USDC per call.

    Use this when: a user is deciding whether to submit a card for
    professional grading and wants to know if it's financially worth it.
    """
    params = {"card_name": card_name, "service_tier": service_tier}
    if raw_price > 0:
        params["raw_price"] = raw_price
    if predicted_grade > 0:
        params["predicted_grade"] = predicted_grade
    return _call_x402("/api/v1/grade-or-not", params)


# ---------------------------------------------------------------------------
# [TCG] Risk Forecast (conformal default) — $0.015
# ---------------------------------------------------------------------------
@mcp.tool()
def simulate_price(
    card_name: str,
    current_price: float,
    model: str = "conformal",
    days: int = 90,
    simulations: int = 20000,
) -> dict:
    """
    Predict future trading card value. The default model is the
    conformal-calibrated risk forecast (deterministic drift + regime-aware
    split-conformal bands, honest VaR/CVaR, plus Safe-Hold & Momentum letter
    grades). Monte Carlo GBM and Merton jump-diffusion are available opt-in
    via model="gbm" or model="merton".

    Returns full forecast percentiles (5th–95th), model parameters,
    and confidence intervals with complete mathematical transparency.

    PAID: $0.015 USDC per call.

    Use this when: a user wants to know "what will this card be worth
    in 3 months?" or wants price trajectory predictions.
    """
    return _call_x402("/api/v1/simulate", {
        "card_name": card_name,
        "current_price": current_price,
        "model": model,
        "days": days,
        "simulations": simulations,
    })


# ---------------------------------------------------------------------------
# [TCG] Card Forecast + Grades — FREE
# ---------------------------------------------------------------------------
@mcp.tool()
def card_forecast(
    card_name: str = "",
    product_id: int = 0,
) -> dict:
    """
    Get the conformal-calibrated 30-day price forecast AND letter grades for a
    single card in ONE free call. Pass either a card_name (resolved to the best
    match) or a TCGplayer product_id.

    FREE — no payment required. Returns an agent-complete object:
      price, as_of, regime, point (median 30d), move_pct, prob_up,
      band50_pct, band90_pct, var95_pct, var99_pct, low90, high90,
      safe_hold grade (A+..F), momentum grade (A+..F or "NA" on a drift spike),
      drift_spike, image_url, card_url, and a one-line plain_english read
      (e.g. "~12% chance it's below $Y in 30 days; Safe-Hold B, Momentum A").

    Use this when a user asks "is this card a safe hold?", "what's the 30-day
    outlook?", "how risky is X?", or wants a quick grade on a card.
    Tip: GET /api/v1/forecast (no args) returns the free board of the top ~200
    cards if the user wants a market overview.
    """
    pid = int(product_id) if product_id else 0
    if not pid:
        if not card_name:
            return {"error": "provide card_name or product_id"}
        hit = _call_x402("/api/v1/search", {"query": card_name, "limit": 1})
        results = (hit.get("data") or {}).get("results") if isinstance(hit, dict) else None
        if not results:
            return {"error": f"no card found for '{card_name}'"}
        pid = results[0]["product_id"]
    return _call_x402(f"/api/v1/forecast/{pid}")


# ---------------------------------------------------------------------------
# [TCG] Trending Cards — $0.025
# ---------------------------------------------------------------------------
@mcp.tool()
def trending_cards(
    game: str = "",
    limit: int = 25,
    min_price: float = 0.0,
) -> dict:
    """
    Top trading cards by 30-day sales volume and price velocity.
    Covers all 13 supported TCG games.

    PAID: $0.025 USDC per call.

    Use this when: a user asks "what cards are hot right now?" or
    "what's selling the most?"
    """
    params = {"limit": min(limit, 100)}
    if game:
        params["game"] = game
    if min_price > 0:
        params["min_price"] = min_price
    return _call_x402("/api/v1/trending", params)


# ---------------------------------------------------------------------------
# [TCG] Arbitrage Scanner — $0.15
# ---------------------------------------------------------------------------
# NOTE (2026-07-21): find_grading_arbitrage was REMOVED before this endpoint
# went public. It called /api/v1/arb-grade, which was deleted from the oracle on
# 2026-07-18 (dead route, 404 — its stale references were pruned from the smoke
# sweep, agent.json and tweet visuals that day). Advertising a tool that errors
# on every call is the opposite of the one-URL-and-it-works pitch this endpoint
# exists to deliver, so the tool count is 10, not 11. Use grade_or_not for the
# per-card "should I grade this?" ROI verdict.


# ---------------------------------------------------------------------------
# [TCG] Portfolio Optimizer — $0.50
# ---------------------------------------------------------------------------
@mcp.tool()
def optimize_portfolio(
    cards: str,
    budget: float = 1000.0,
    risk_tolerance: str = "moderate",
    days: int = 90,
) -> dict:
    """
    Optimize a trading card portfolio using Markowitz mean-variance
    analysis with Merton jump-diffusion Monte Carlo simulations.

    Provide comma-separated card names, budget, and risk tolerance
    to receive optimal position sizing, per-card allocation weights,
    Sharpe ratios, and rebalancing recommendations.

    PAID: $0.50 USDC per call.

    Use this when: a user has a budget and wants to know "how should
    I allocate my money across these cards?"
    """
    return _call_x402("/api/v1/portfolio-optimize", {
        "cards": cards,
        "budget": budget,
        "risk_tolerance": risk_tolerance,
        "days": days,
    })


# ---------------------------------------------------------------------------
# [META] Workflow Advisor — FREE
# ---------------------------------------------------------------------------
@mcp.tool()
def recommend_workflow(goal: str) -> dict:
    """
    Describe your goal in natural language and get a recommended sequence
    of TCG Oracle API calls to accomplish it.

    FREE — no payment required.

    Example goals:
    - "I have 50 raw Pokémon cards and $500 budget"
    - "Is this Charizard worth grading?"
    - "Find me undervalued cards to flip"
    - "Predict the price of a Black Lotus in 90 days"

    Use this when: you're not sure which tool to call first, or need
    a multi-step workflow recommendation.
    """
    return _call_x402("/api/v1/recommend", {"goal": goal}, method="POST")


# ---------------------------------------------------------------------------
# [META] Prediction Accuracy — FREE
# ---------------------------------------------------------------------------
@mcp.tool()
def check_accuracy(game: str = "") -> dict:
    """
    View TCG Oracle's public prediction accuracy dashboard.
    Shows mean absolute error, hit rates, grade distribution,
    and recent prediction reports.

    FREE — no payment required.

    Use this when: a user asks "how accurate is the grading AI?"
    or wants to verify the model's track record.
    """
    params = {}
    if game:
        params["game"] = game
    return _call_x402("/api/v1/accuracy", params)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TCG Oracle Remote MCP Server")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--transport", default=TRANSPORT, choices=["sse", "streamable-http"])
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    # mcp>=1.x FastMCP.run() takes only (transport, mount_path); host/port live
    # on .settings. Passing them to run() raises TypeError and the server never
    # binds — caught on the 2026-07-21 deploy before it reached the tunnel.
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    print(f"🚀 TCG Oracle MCP Remote Server")
    print(f"   Transport: {args.transport}")
    print(f"   Bind: {args.host}:{args.port}")
    print(f"   x402 Backend: {X402_BASE}")
    print(f"   Tools: 10 (search, market, grade, grade-or-not, simulate, card_forecast, trending, portfolio, recommend, accuracy)")
    print()

    if args.transport == "streamable-http":
        # Serve the SAME app at BOTH "/" and "/mcp". The subdomain already says
        # "mcp", so `mcp.the-undesirables.com/mcp` stutters — the clean root URL
        # is what we publish. /mcp stays mounted because it is the SDK's default
        # and some clients/directories probe it by convention; a dev who types it
        # from habit must not get a 404.
        import uvicorn

        # App is rooted at "/" (the clean public URL). A tiny ASGI shim aliases
        # /mcp and /mcp/ onto it. Nested Starlette Mounts don't work here: an
        # exact "/mcp" yields an EMPTY sub-path rather than "/", so the inner
        # route misses and 404s (and it would redirect a POST). Rewriting the
        # path is unambiguous and keeps lifespan/websocket scopes untouched.
        mcp.settings.streamable_http_path = "/"
        inner = mcp.streamable_http_app()

        class _AliasMcpPath:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                if scope.get("type") == "http" and scope.get("path") in ("/mcp", "/mcp/"):
                    scope = dict(scope, path="/", raw_path=b"/")
                await self.app(scope, receive, send)

        app = _AliasMcpPath(inner)
        print(f"   Public URL: https://{PUBLIC_HOST}        (alias: /mcp)")
        print(f"   Perplexity: Settings → Connectors → + Custom → Remote")
        print()
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        print(f"   Public URL: https://{PUBLIC_HOST}{mcp.settings.sse_path}")
        print()
        mcp.run(transport=args.transport)
