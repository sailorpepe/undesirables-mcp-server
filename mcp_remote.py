#!/usr/bin/env python3
"""
TCG Oracle — Remote MCP Server (SSE Transport)
===============================================
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
    python mcp_remote.py                       # Start SSE on port 8443
    python mcp_remote.py --port 9000           # Custom port
    python mcp_remote.py --transport streamable-http  # Modern transport

Perplexity Setup:
    Settings → Connectors → + Custom Connector → Remote
    URL: https://your-domain.com/sse
    Transport: SSE
    Auth: None (or API key if configured)
"""

import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
X402_BASE = os.getenv("X402_BASE_URL", "http://localhost:8402")
PORT = int(os.getenv("MCP_REMOTE_PORT", "8443"))
TRANSPORT = os.getenv("MCP_REMOTE_TRANSPORT", "sse")

mcp = FastMCP(
    "TCG Oracle",
    instructions=(
        "Financial intelligence API for the $50B+ trading card market. "
        "Search 370K+ products across 25 games, grade card images with AI, "
        "forecast prices with Monte Carlo simulation, and get ROI verdicts "
        "on whether to send cards for professional grading. "
        "All data comes from TCGCSV daily market snapshots and real-time analysis."
    ),
)


# ---------------------------------------------------------------------------
# Helper: Call x402 server endpoints
# ---------------------------------------------------------------------------
def _call_x402(path: str, params: dict = None, method: str = "GET") -> dict:
    """Call the local x402 server. Free endpoints don't need payment."""
    try:
        url = f"{X402_BASE}{path}"
        with httpx.Client(timeout=30.0) as client:
            if method == "POST":
                r = client.post(url, json=params or {})
            else:
                r = client.get(url, params=params or {})
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
    Search 370,158 TCG products across 25 card games.
    Returns card names, sets, and current market prices.
    FREE — no payment required.

    Use this when: a user asks about a specific card, wants to find cards,
    or needs current pricing for any trading card game product.
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
    and volume leaders across all 25 supported card games.
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
# [TCG] Monte Carlo Price Forecast — $0.015
# ---------------------------------------------------------------------------
@mcp.tool()
def simulate_price(
    card_name: str,
    current_price: float,
    model: str = "heston",
    days: int = 90,
    simulations: int = 20000,
) -> dict:
    """
    Predict future trading card value using stochastic finance Monte Carlo.
    Supports Heston (stochastic volatility), Merton (jump-diffusion),
    and Kou (double-exponential jumps) models.

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
    Covers all 25 supported TCG games.

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
@mcp.tool()
def find_grading_arbitrage(
    game: str = "Pokemon",
    min_roi: float = 50.0,
    min_raw_price: float = 5.0,
    max_raw_price: float = 500.0,
) -> dict:
    """
    Scans the TCG database for undervalued raw cards where professional
    grading would produce ROI above your threshold. Estimates PSA grades
    based on price tier and rarity, calculates expected graded values.

    Returns ranked opportunities sorted by expected profit.

    PAID: $0.15 USDC per call.

    Use this when: a user asks "what cheap cards should I buy and grade
    for profit?" or "find me undervalued cards to flip."
    """
    return _call_x402("/api/v1/arb-grade", {
        "game": game,
        "min_roi": min_roi,
        "min_raw_price": min_raw_price,
        "max_raw_price": max_raw_price,
    })


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
    analysis with Kou jump-diffusion Monte Carlo simulations.

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

    print(f"🚀 TCG Oracle MCP Remote Server")
    print(f"   Transport: {args.transport}")
    print(f"   Port: {args.port}")
    print(f"   x402 Backend: {X402_BASE}")
    print(f"   Tools: 10 (search, market, grade, grade-or-not, simulate, trending, arb-grade, portfolio, recommend, accuracy)")
    print()
    print(f"   Perplexity: Settings → Connectors → + Custom → Remote")
    print(f"   URL: https://your-domain.com/{args.transport.replace('streamable-', '')}")
    print()

    mcp.run(transport=args.transport, host=args.host, port=args.port)
