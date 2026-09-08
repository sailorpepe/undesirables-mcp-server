#!/usr/bin/env python3
"""
The Undesirables TCG Oracle — local stdio MCP server (the default entry point).

One focused surface: the 22 oracle tools — search 455K+ trading cards, live
market snapshots, AI grading and grade-or-not decisions, conformal-calibrated
price forecasts with a public accuracy scorecard, portfolio optimisation,
card-collateral loan terms, the fantasy and sports souls leagues, the
Syndicate game, and the Technocore rooms — everything proven on-chain.

It is the SAME tool set the hosted endpoint serves at
https://mcp.the-undesirables.com/mcp — this file just runs it over stdio for
IDEs and desktop clients (Claude Desktop, Cursor, Zed, ...):

    uvx undesirables-mcp-server          # after `pip install undesirables-mcp-server`
    python oracle_server.py              # from a checkout

The data comes from the public oracle API (X402_BASE_URL, default
https://oracle.the-undesirables.com); no keys, no wallet, no local models.
Free tools answer directly; paid tools return the x402 payment terms.

The local AGENT KIT (memory graph, media generation, voice, code execution,
security audits — 34 tools) lives in server.py and is a separate entry point:

    undesirables-agent-kit
"""
import sys

from mcp_remote import mcp  # the 22 oracle tools, registered once, shared with the hosted server


def main():
    # stdio is the protocol channel: keep every human message on stderr
    print("The Undesirables TCG Oracle — MCP over stdio (22 tools, no keys)", file=sys.stderr, flush=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
