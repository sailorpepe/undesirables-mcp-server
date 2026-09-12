<!-- mcp-name: io.github.sailorpepe/undesirables-mcp-server -->

<div align="center">

![The Undesirables MCP Banner](https://raw.githubusercontent.com/sailorpepe/undesirables-mcp-server/main/og_preview.png)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/powered%20by-FastMCP-green.svg?style=flat-square)](https://github.com/modelcontextprotocol/fastmcp)
[![License: BSL-1.1](https://img.shields.io/badge/License-BSL_1.1-orange.svg?style=flat-square)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/undesirables-mcp-server.svg?style=flat-square)](https://pypi.org/project/undesirables-mcp-server/)

**The TCG Oracle as an MCP server: 22 focused tools, the same ones the hosted endpoint serves — plus a separate 34-tool local agent kit**

*Install the package and the default command is the oracle over stdio (no keys, no wallet, no local models), or connect to the hosted endpoint at `mcp.the-undesirables.com`. Free tools answer directly; paid tools return x402 terms — pay-per-call in USDC, no account or API key.*

[Website](https://the-undesirables.com) · [Docs](https://the-undesirables.com/docs) · [PyPI](https://pypi.org/project/undesirables-mcp-server/) · [𝕏](https://x.com/undesirables_ai)

</div>

<div align="center">

<img src="https://raw.githubusercontent.com/sailorpepe/undesirables-mcp-server/main/assets/demo.gif" alt="Undesirables MCP Server Demo" width="480" />

</div>

---

## 🔌 Connect over MCP — one URL, no install

```
https://mcp.the-undesirables.com

Newest hosted tools (Sept 2026): `fantasy_league` — 4,444 AI personalities
drafting weekly fantasy lineups, merkle-committed before games score ·
`loan_terms_preview` — the Loan-Terms Oracle's six-step max-LTV derivation for
card collateral · `oracle_scorecard` — our public 30-day coverage record
(93%+ on 181K+ matured forecasts, committed on-chain before outcomes).
```

No install, no account, no API key. **22 tools** over streamable HTTP (MCP protocol
`2025-06-18`; legacy SSE also served). Free tools answer immediately. Paid tools return an
x402 `payment_required` carrying amount, network, and `payTo` — an agent with a funded
wallet can settle and retry in the same session. Settlement only occurs on a successful
response; failed calls are never charged.

Holders can also ask **which Undesirables a wallet owns** and how each soul's calls have
scored (`souls_in_wallet`, `soul_calls`) — public track record only; personalities stay
holder-gated.

**Claude Desktop / Perplexity** — add it as a custom remote connector (Perplexity:
Settings → Connectors → + Custom Connector → Remote).

**Cursor / Windsurf / VS Code** — clients that take a URL in config:

```json
{
  "mcpServers": {
    "tcg-oracle": { "url": "https://mcp.the-undesirables.com" }
  }
}
```

Tools: `search_tcg_products`, `market_snapshot`, `grade_card`, `grade_or_not`,
`simulate_price`, `card_forecast`, `trending_cards`, `optimize_portfolio`,
`recommend_workflow`, `oracle_scorecard`.

Search is set-aware — `search_tcg_products("Base Set Charizard")` separates Base Set,
Base Set 2, and Shadowless rather than returning every Charizard printing. Every result
carries a `set` field and a `product_id` you can pass straight to the other tools.

---

## Two servers, one package (v2.0.0)

| Command | What it exposes | For |
|---|---|---|
| `undesirables-mcp` (default) | **The TCG Oracle — 22 tools**: search 456K+ cards (USD prices frozen 2026-09-07 — responses carry `usd_panel`), market snapshots (suspended while frozen), AI grading & grade-or-not, conformal-calibrated forecasts with a public accuracy scorecard, portfolio optimisation, card-collateral loan terms, fantasy & sports souls, the Syndicate, Technocore rooms. Backed by the public oracle API. | Anyone who wants the oracle in Claude Desktop, Cursor, Zed, LangChain… |
| `undesirables-agent-kit` | **The local agent kit — 34 tools**: memory graph, RAG over a soul workspace, meme/banner/video/3D generation, voice, code & shell execution, security audits, web search. Runs entirely on your machine. | Undesirables holders running their soul as a local agent |

v1.x shipped both surfaces under one command; v2 separates them so each server has one job. The hosted endpoint is unchanged.

## Quick Install

```bash
pip install undesirables-mcp-server

undesirables-mcp          # the TCG Oracle over stdio (22 tools, no keys) — default
undesirables-agent-kit    # the local 34-tool agent kit
```

Claude Desktop / Cursor / Zed — add the oracle as a stdio server:

```json
{ "mcpServers": { "undesirables-oracle": { "command": "uvx", "args": ["undesirables-mcp-server"] } } }
```

> **Turn any Undesirable NFT into an MCP-compatible AI agent with the 34-tool local agent kit (`undesirables-agent-kit`).**

---

## Table of Contents

- [What It Does](#what-it-does)
- [What's New](#whats-new-in-v210--v20x)
- [The Local Agent Kit](#-the-local-agent-kit-undesirables-agent-kit)
- [Technical Architecture (agent kit)](#technical-architecture-agent-kit)
- [Agent Framework Integration](#agent-framework-integration)
- [LitVM TCG Oracle](#litvm-tcg-oracle--mcp-server)
- [Ecosystem](#the-undesirables-ecosystem)
- [License & Commercial Use](#-license--commercial-use)

---

## What It Does

### The TCG Oracle — `undesirables-mcp` (default), 22 tools, no keys

The same 22 tools the hosted endpoint serves, over stdio. Free tools answer directly; paid tools return x402 terms (USDC on Base or Solana, USDG on Robinhood Chain) and are only charged on a successful response.

| Area | Tools |
|---|---|
| 🔎 **Search & prices** | `search_tcg_products` (455K+ products, 25+ games, set-aware), `market_snapshot`, `trending_cards` |
> **USD panel frozen 2026-09-07.** `market_snapshot`, `simulate_price`, `trending_cards` and `optimize_portfolio` are suspended (the oracle returns `{"status":"suspended"}` and does not charge); `card_forecast` and `search_tcg_products` serve the last published USD numbers and say so in-band. Live: graded-slab loan terms, sports, souls, census, crypto, Japanese two-sided quotes.

| 📊 **Forecasts & risk** | `card_forecast` (FREE: conformal 30-day forecast + Safe-Hold / Momentum letter grades), `simulate_price` (**suspended while the USD panel is frozen** — answers `{status: suspended}`, no charge; Monte Carlo GBM / Merton paths), `optimize_portfolio` |
| 🎴 **Grading** | `grade_card` (3-stage vision pipeline, PSA/Beckett-calibrated), `grade_or_not` (GO / NO-GO with expected ROI) |
| 🧾 **Public track record** | `oracle_scorecard` (30-day coverage on 181K+ matured forecasts, committed on-chain before outcomes) |
| 🏦 **Card collateral** | `loan_terms_preview` (the Loan-Terms Oracle's six-step max-LTV derivation) |
| 👻 **Souls & leagues** | `souls_in_wallet`, `soul_calls`, `fantasy_league` (4,444 AI personalities drafting weekly lineups), `sports_board` |
| 🕹️ **The Syndicate** | `syndicate_state`, `syndicate_move`, `syndicate_leaderboard` — a turn-based strategy game agents can play |
| 💬 **technocore.chat (read-only)** | `technocore_rooms`, `technocore_room`, `technocore_info`, `technocore_note` |
| 🧭 **Routing** | `recommend_workflow` — describe a goal, get the call sequence |

### The local agent kit — `undesirables-agent-kit`, 34 tools, runs on your machine

Turns an Undesirable NFT soul workspace into a local agent: persistent memory graph and RAG over the soul files, meme / banner / image / video / 3D generation, Kokoro TTS, ACE Step music, DuckDuckGo search, SAST code auditing, Ollama prompting, sandboxed code and shell execution, and eBay market depth. It needs Ollama and a soul workspace — see [The Local Agent Kit](#-the-local-agent-kit-undesirables-agent-kit) below. The oracle needs none of that.

---

<details>
<summary><strong>What's New in v2.1.0 / v2.0.x</strong></summary>

**2.1.0** — `check_accuracy` removed. It returned exactly what `oracle_scorecard` returns (same endpoint) and ignored its `game` argument, so it only existed to confuse an agent choosing between the two. Callers: switch to `oracle_scorecard`. The oracle is 22 tools.

**2.0.1** — tool descriptions rewritten so overlapping pairs state distinct jobs (`card_forecast` = free fixed 30-day read, `simulate_price` = paid custom horizon + full distribution; `market_snapshot` = the day's market report, `trending_cards` = ranked pick list; the four `technocore_*` readers numbered 1-4). `check_accuracy` is now a documented deprecated alias of `oracle_scorecard` (same data; removal planned for 2.1).

- **The oracle is the default server.** `undesirables-mcp` (and `undesirables-mcp-server`) now start the 22-tool TCG Oracle over stdio — the same tools as `https://mcp.the-undesirables.com`, with no keys, wallet, or local models.
- **The agent kit has its own command.** The 34-tool local kit moved to `undesirables-agent-kit`. Nothing was removed; each server now has one job.
- **Dependencies pinned** to `fastmcp<4` and `mcp<2` so fresh installs keep working across SDK major bumps.
- Newest oracle tools (Sept 2026): `fantasy_league`, `loan_terms_preview`, `oracle_scorecard`, `sports_board`, the Syndicate trio, and the technocore.chat readers.
- Carried over from v1.1.8: the FREE `card_forecast(card_name | product_id)` — conformal 30-day forecast plus Safe-Hold & Momentum grades in one call.

</details>

---

## 🧰 The Local Agent Kit (`undesirables-agent-kit`)

> Everything in this section is for the **agent kit only**. If you just want the oracle, you're already done: `uvx undesirables-mcp-server` (or the hosted URL above).

### 🛑 Prerequisites
1. **[Python](https://www.python.org/downloads/)** 3.10 or higher.
2. **[Ollama](https://ollama.com/)** — download it *and run it*. The llama icon must be in your menu bar / taskbar, or local inference fails immediately.
3. A **soul workspace** folder downloaded from [the-undesirables.com](https://the-undesirables.com) (for example `soul_folder/0420`).

### 🛠️ Install

```bash
pip install undesirables-mcp-server
```

Or, to hack on it:

```bash
git clone https://github.com/sailorpepe/undesirables-mcp-server.git
cd undesirables-mcp-server
python3 -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 🚀 Boot

```bash
# point --workspace at your EXACT soul folder
undesirables-agent-kit --workspace "/Users/you/Desktop/soul_folder/0420"
```

(From a clone: `python server.py --workspace ".../soul_folder/0420"`.) The server has no chat window — it speaks JSON-RPC to whatever client you connect next. Don't type into that terminal.

### 🔌 Connect Claude Desktop

**Settings → Developer → Edit Config**, then:

```json
{
  "mcpServers": {
    "undesirables-agent-kit": {
      "command": "undesirables-agent-kit",
      "args": ["--workspace", "/Users/you/Desktop/soul_folder/0420"]
    }
  }
}
```

Restart Claude Desktop; the tools icon should show 34 Undesirables tools. Cursor, Zed, and Windsurf take the same `command` / `args` shape.

### 🎨 Local image generation (optional)

The kit uses the 16 GB `FLUX.1-schnell` model for fully offline memes and illustrations. Skip this step (or run on a machine with under 12 GB RAM) and it silently falls back to the free Pollinations.ai cloud.

- **Apple Silicon** uses `mflux`, which needs a Hugging Face token for Black Forest Labs' gated repo: accept the terms at [black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell), create a **Read** token at [Hugging Face Tokens](https://huggingface.co/settings/tokens), then run `python -c "import huggingface_hub; huggingface_hub.login()"` and paste it.
- **Nvidia CUDA / AMD DirectML** are detected automatically and use the ungated `shuttleai/FLUX.1-schnell` weights — no account needed; the first `generate a meme` downloads them.

### ⚠️ Troubleshooting

- **Ollama connection refused** — Ollama isn't running. Launch the app and check for the llama icon.
- **ModuleNotFoundError: fastmcp** — you're outside the virtual environment (clone installs only). `source venv/bin/activate` first.
- **Invalid JSON: expected value at line 1** — you typed into the server terminal. Leave it alone and talk through Claude Desktop / Cursor.

---

## Technical Architecture (agent kit)

This section describes `undesirables-agent-kit`. (The oracle is a thin stdio wrapper over the same 22 tools the hosted endpoint serves; nothing below applies to it.)

The agent kit exposes your local NFT soul via the [Model Context Protocol](https://modelcontextprotocol.io) standard.

**Resources** (read only context your AI can access):
- `soul://personality` — Big Five scores, archetype, strategy, fatal flaw
- `soul://system-prompt` — The full system prompt that defines the agent
- `soul://memory` — Persistent memory (trade history, observations)
- `soul://predictions` — Prediction ledger with grades

**Agent kit tools** (34 functions your AI can call — `undesirables-agent-kit`):
- `grade_tcg_card` — 3-stage PSA/Beckett grading: Qwen Vision LLM + OpenCV centering + BGS capping
- `card_forecast` — **FREE** one-call conformal 30-day forecast + Safe-Hold/Momentum letter grades + plain-English read (pass a card name or TCGplayer product_id)
- `monte_carlo_simulation` — Price forecasting: conformal-calibrated risk by default (honest VaR/CVaR + Safe-Hold/Momentum grades); Monte Carlo GBM/Merton opt-in
- `search_ebay_market` — Live eBay market depth, price distributions, arbitrage detection
- `purchase_undesirables_license_key` — M2M purchase bridge (EVM tx payload)
- `verify_soul_initialization` — On chain soul verification
- `generate_voice` — Kokoro TTS voice synthesis
- `generate_3d_object` — Shap E text to 3D mesh (.glb)
- `generate_image` — Local FLUX image generation
- `web_search` — DuckDuckGo instant answers
- `run_security_audit` — SAST code scanning
- `query_ollama` — Send prompts to local Ollama
- `analyze_market` — Run market analysis in character
- `create_content` — Write tweets, threads, bios in character
- `meme_machine` — Generate meme concepts and marketing content
- And 20+ more covering video, audio, memory, sandbox execution

```
┌─────────────────────────────────────────────┐
│           MCP Client (Cursor, Claude)       │
└──────────────────┬──────────────────────────┘
                   │ JSON-RPC (stdio)
┌──────────────────▼──────────────────────────┐
│        Undesirables MCP Server              │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │Resources │ │  Tools   │ │  Prompts   │  │
│  │SOUL.md   │ │Skills    │ │Templates   │  │
│  │MEMORY.md │ │Ollama    │ │            │  │
│  │Predictions│ │Analysis │ │            │  │
│  └──────────┘ └────┬─────┘ └────────────┘  │
└────────────────────┼────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────┐
│              Ollama (Local LLM)             │
│           llama3.1:8b / qwen / etc          │
└─────────────────────────────────────────────┘
```

## Agent Framework Integration

### LangChain / LangGraph
```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient({
    "undesirables": {
        "command": "uvx",
        "args": ["undesirables-mcp-server"]
    }
}) as client:
    tools = client.get_tools()
    # the 22 oracle tools, now available to any LangChain agent
    # (for the agent kit use command="undesirables-agent-kit", args=["--workspace", ".../soul_folder/0420"])
```

### CrewAI
```python
from crewai import Agent
from crewai_tools import MCPServerAdapter

mcp = MCPServerAdapter(
    command="uvx", args=["undesirables-mcp-server"])

agent = Agent(
    role="NFT Card Grader",
    tools=mcp.tools,
    goal="Grade trading cards and run calibrated price forecasts"
)
```

### OpenAI Agents SDK
```python
from agents import Agent
from agents.mcp import MCPServerStdio

mcp_server = MCPServerStdio(
    command="uvx", args=["undesirables-mcp-server"])

agent = Agent(
    name="Undesirables Agent",
    instructions="You are a TCG market analyst. Use the oracle tools for prices, forecasts, and grading.",
    mcp_servers=[mcp_server]
)
```

### ElizaOS (Merged into Official Monorepo)
```bash
npm install plugin-undesirables
```
The plugin is now part of the [official ElizaOS monorepo](https://github.com/elizaOS/eliza/tree/develop/plugins/plugin-undesirables) (PR #7869, merged May 21 2026).

Add to your `character.json`:
```json
{
  "settings": {
    "UNDESIRABLES_WORKSPACE": "/path/to/soul_folder/0420"
  },
  "plugins": ["plugin-undesirables"]
}
```

---

## LitVM TCG Oracle — MCP Server

We also publish a dedicated on-chain oracle MCP server for the LitecoinVM ecosystem:

```bash
pip install litvm-tcg-oracle
```

| Feature | Detail |
|---------|--------|
| **456K+ trading cards** | 25+ games, 290K actively priced |
| **13.5M+ price observations** | 60+ days of continuous data |
| **On-chain Merkle proofs** | Trustless verification on LiteForge (Chain 4441) |
| **Risk forecast** | Conformal-calibrated VaR/CVaR + Safe-Hold/Momentum grades (Monte Carlo opt-in) |
| **13 MCP tools** | `search_cards`, `get_price`, `get_merkle_proof`, `get_graded_proof`, `oracle_status`, `get_forecast`, `simulate_price`, `get_market_snapshot`, `get_fantasy_league`, `get_oracle_scorecard`, `get_loan_terms_preview`, `get_sports_board`, `get_census_summary` — also hosted at `https://litvm.the-undesirables.com/mcp` |

→ **GitHub**: [litvm-tcg-oracle-mcp](https://github.com/sailorpepe/litvm-tcg-oracle-mcp)  
→ **PyPI**: [litvm-tcg-oracle](https://pypi.org/project/litvm-tcg-oracle/)  
→ **Live Oracle**: [the-undesirables.com/litvm](https://the-undesirables.com/litvm)

---

## The Undesirables Ecosystem

- **Website**: [the-undesirables.com](https://the-undesirables.com)
- **LitVM Oracle**: [the-undesirables.com/litvm](https://the-undesirables.com/litvm)
- **Mint**: [scatter.art/the-undesirables](https://scatter.art/the-undesirables)
- **Docs**: [the-undesirables.com/docs](https://the-undesirables.com/docs)
- **PyPI (MCP)**: [undesirables-mcp-server](https://pypi.org/project/undesirables-mcp-server/) (v2.0.0)
- **PyPI (LitVM)**: [litvm-tcg-oracle](https://pypi.org/project/litvm-tcg-oracle/) (v1.0.7)
- **npm**: [plugin-undesirables](https://npmjs.com/package/plugin-undesirables) (ElizaOS plugin, v2.7.0)
- **Oracle API**: [oracle.the-undesirables.com](https://oracle.the-undesirables.com) (31 endpoints, x402 micropayments)
- **awesome-mcp-servers**: [Listed ✅](https://github.com/punkpeye/awesome-mcp-servers) (94K+ ⭐, both servers listed)
- **Glama**: [Verified ✅ — tool quality A, 22 tools](https://glama.ai/mcp/servers/sailorpepe/undesirables-mcp-server)
- **ElizaOS Plugin**: [Official monorepo](https://github.com/elizaOS/eliza/tree/develop/plugins/plugin-undesirables)
- **x402 Payment Server**: [undesirables-x402-server](https://github.com/sailorpepe/undesirables-x402-server)
- **Price data**: originates with TCGplayer. No rights claimed in the underlying prices;
  the modelling and on-chain proofs are ours.
- **X**: [@undesirables_ai](https://x.com/undesirables_ai)

---

## ⚖️ Legal Disclaimer

**For Entertainment Purposes Only:** The Market Oracle, Trading Simulators, and all AI-generated predictions are for educational and entertainment purposes. AI models natively hallucinate. Do not use this Server to execute live financial trades or make purchasing business decisions. The Undesirables LLC operates a zero-liability framework for deployed open-source AI tooling.

---

## 📝 License & Commercial Use

This project is licensed under the **[Business Source License 1.1 (BUSL-1.1)](LICENSE)**.

We build in public and support the developer ecosystem — but we also protect the infrastructure and IP of **The Undesirables LLC**.

### ✅ What You CAN Do (Free)

- **Personal & Educational Use** — Download, modify, and run locally for learning, research, or personal projects.
- **Non-Competing Applications** — Integrate our packages into your app, provided your app does not offer TCG market intelligence, pricing aggregation, AI card grading, or on-chain price oracle services as its primary function.
- **MCP / Agent Integration** — Connect your AI agent to our tools for non-commercial use.
- **Community Contributions** — Security audits, bug fixes, and PRs are always welcome.

### 🚫 What You CANNOT Do (Use Limitation)

- **Competing Service** — You may not use this code to operate a competing TCG market intelligence, pricing aggregation, AI card grading, or on-chain price oracle service.
- **Commercial Resale** — You may not wrap our API, data pipelines, or AI models into a paid service without a commercial license.
- **Hosted SaaS** — You may not host this software as a service for third parties without written permission.

### 🔓 Open-Source Conversion

On **June 1, 2030** (or 4 years after the first public release of each version), this code automatically converts to the **MIT License** — fully open source, forever.

### 🤝 Commercial Licensing

Building a commercial product? Want guaranteed API access or white-label integration? Contact us:

📧 **oracle@the-undesirables.com** · 🐦 **[@undesirables_ai](https://x.com/undesirables_ai)**

© 2026 The Undesirables LLC

---

<div align="center">

⭐ **If this project helped you, please star this repo** — it helps others find it.

[Report Bug](../../issues) · [Request Feature](../../issues)

</div>

## Data freshness

USD market prices originate from TCGPlayer. **That upstream feed is currently unavailable, so USD prices are frozen at their last good date.** Every price response carries its own `latest_date`, and the oracle root publishes live panel state under `panels` — read that rather than assuming.

A Japanese-print panel refreshes every morning: 24 games, ~364K cards, ~167K of them carrying **both** an asking price and a dealer buyback bid. Graded comps, sports boards and the proof layer are unaffected.

We claim no rights in any underlying price data and redistribute no provider's dataset.
