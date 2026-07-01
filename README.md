<!-- mcp-name: io.github.sailorpepe/undesirables-mcp-server -->

<div align="center">

![The Undesirables MCP Banner](https://raw.githubusercontent.com/sailorpepe/undesirables-mcp-server/main/og_preview.png)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/powered%20by-FastMCP-green.svg?style=flat-square)](https://github.com/modelcontextprotocol/fastmcp)
[![License: BSL-1.1](https://img.shields.io/badge/License-BSL_1.1-orange.svg?style=flat-square)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/undesirables-mcp-server.svg?style=flat-square)](https://pypi.org/project/undesirables-mcp-server/)

**35+ local compute tools for AI agents — zero cloud dependency**

[Website](https://the-undesirables.com) · [Docs](https://the-undesirables.com/docs) · [PyPI](https://pypi.org/project/undesirables-mcp-server/) · [𝕏](https://x.com/undesirables_ai)

</div>

<div align="center">

<img src="https://raw.githubusercontent.com/sailorpepe/undesirables-mcp-server/main/assets/demo.gif" alt="Undesirables MCP Server Demo" width="480" />

</div>

---

## Quick Install

```bash
pip install undesirables-mcp-server
```

> **Turn any Undesirable NFT into an MCP-compatible AI agent with 35+ local compute tools.**

---

## Table of Contents

- [What It Does](#what-it-does)
- [What's New in v1.1.8](#whats-new-in-v118)
- [Prerequisites](#-prerequisites-read-carefully)
- [Full Setup](#-step-1-install--clone)
- [Boot The Server](#-step-2-boot-the-server)
- [Connect Your Chat Front-End](#-step-3-connect-your-chat-front-end)
- [Local Image Generation](#-step-4-setup-local-image-generation-optional)
- [Troubleshooting](#%EF%B8%8F-common-idiot-proof-diagnostics)
- [Technical Architecture](#technical-architecture-for-developers)
- [Agent Framework Integration](#agent-framework-integration)
- [LitVM TCG Oracle](#litvm-tcg-oracle--mcp-server)
- [Ecosystem](#the-undesirables-ecosystem)
- [License & Commercial Use](#-license--commercial-use)

---

## What It Does

- 🎴 **Vision AI Card Grading** — PSA/Beckett prediction via Qwen VL
- 📊 **Conformal Risk Forecast** — calibrated VaR/CVaR + Safe-Hold & Momentum letter grades (Monte Carlo GBM/Merton opt-in)
- 🎵 **AI Music Generation** — ACE Step on Apple Silicon
- 🎬 **Video Clipping & Beat Sync Editing** — FFmpeg
- 🖼️ **Local Image Generation** — MLX Flux on Mac, DirectML on Windows, CUDA on Linux
- 🗣️ **Text to Speech Voice Engine** — Kokoro TTS
- 🧠 **Persistent RAG Memory Graphs** — CRM node mapping
- 🔍 **Zero Token Web Search** — DuckDuckGo
- 🔒 **SAST Code Security Auditing**
- 📈 **Financial Analytics Oracle** — TCGCSV + eBay depth analysis

---

<details>
<summary><strong>What's New in v1.1.8</strong></summary>

**v1.1.8** adds the FREE `card_forecast(card_name | product_id)` tool — one call returns the conformal 30-day price forecast **plus Safe-Hold & Momentum letter grades** and a one-line plain-English read (e.g. _"~12% chance it's below $Y in 30 days; Safe-Hold B, Momentum A"_). No payment required.

The **conformal-calibrated risk forecast** is the default model — regime-aware split-conformal bands with honest VaR/CVaR, plus Safe-Hold & Momentum letter grades. Monte Carlo (GBM / Merton Jump-Diffusion) remains available opt-in via `model=`. Also: corrected license badge and full ecosystem integration.

**Key Features:**
- `purchase_undesirables_license_key` — Returns an unsigned EVM transaction payload (Ethereum Mainnet, chainId 1) for autonomous agents to mint directly from the Scatter.art contract
- `verify_soul_initialization` — Verifies on chain purchase via public RPC and initializes the cryptographic soul matrix, unlocking all local compute engines
- Verified on [Glama.ai](https://glama.ai/mcp/servers/sailorpepe/undesirables-mcp-server) with a 3.8/5 quality score across 36 tools
- Listed on 9+ MCP directories including the [Official MCP Registry](https://registry.modelcontextprotocol.io)

</details>

---

## 🛑 Prerequisites (Read Carefully)
If you've never used Python or run AI Models locally, you **must** do this first:
1. **[Download Python](https://www.python.org/downloads/)** (Version 3.10 or higher).
2. **[Download Ollama](https://ollama.com/)**. **CRITICAL:** You cannot just download the app and leave it in your downloads folder. You must double-click the Ollama app to *physically run it*. You should see a little llama icon in your Mac menu bar or Windows system tray for this server to work. 

---

## 🛠️ Step 1: Install & Clone

First, open your Terminal or Command Prompt and clone this repository. After cloning, you must activate a "Virtual Environment" (a sandbox folder just for this codebase).

### 🍎 On Mac / Linux
```bash
git clone https://github.com/sailorpepe/undesirables-mcp-server.git
cd undesirables-mcp-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 🪟 On Windows
```bash
git clone https://github.com/sailorpepe/undesirables-mcp-server.git
cd undesirables-mcp-server
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

## 🚀 Step 2: Boot The Server

Every single time you want to run this server later, you must open your terminal and make sure your Virtual Environment is activated `(venv)` first!

If you already downloaded your Soul Workspace from the website:
```bash
# Make sure to point to your EXACT soul folder path
python server.py --workspace "/Users/username/Desktop/soul_folder/0420"
```

---

## 🔌 Step 3: Connect Your Chat Front-End

The MCP Server doesn't have a chat window; it runs invisibly in the background of your terminal! To actually talk to your agent, you must connect it to a desktop application like Claude or Cursor.

### Claude Desktop Connection
1. Open the Claude Desktop application on your computer.
2. Go to **Settings > Developer > Edit Config**.
3. Paste this into your config file, making absolutely sure you replace the `cwd` (Current Working Directory) with your exact folder path:
```json
{
  "mcpServers": {
    "undesirables": {
      "command": "python",
      "args": ["server.py", "--workspace", "/Users/yourname/Desktop/soul_folder/0420"],
      "cwd": "/Users/yourname/Documents/undesirables-mcp-server"
    }
  }
}
```
4. Restart the Claude Desktop app. You should see a little "Plugin/Hammer" icon telling you that 35+ The Undesirables tools are now available!

---

## 🎨 Step 4: Setup Local Image Generation (Optional)

If you want your agent to physically generate memes and illustrations 100% offline natively on your computer, the MCP Server uses the massively powerful 16GB `FLUX.1-schnell` model. 

If you do not complete this step, or if your computer is too weak (< 12GB RAM), the server will automatically fallback and generate memes for you silently via the free `Pollinations.ai` cloud network.

### 🍏 Authenticating Apple Silicon (Mac M1/M2/M3/M4)
Apple Silicon specifically uses `mflux`, which strictly requires a Hugging Face token to bypass Black Forest Labs' legal compliance gate.
1. Navigate to **[black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell)**, create a free Hugging Face account, and click **Agree and Access**.
2. Go to **[Hugging Face Tokens](https://huggingface.co/settings/tokens)** and generate a new **Read** token.
3. Open your Mac terminal, activate your virtual environment, and log in:
```bash
cd undesirables-mcp-server
source venv/bin/activate
python -c "import huggingface_hub; huggingface_hub.login()"
```
4. Paste your token and press **Enter** *(your clipboard characters will be invisible for security)*.

### 🪟 Setup for Windows/Linux GPUs
If your computer uses Nvidia CUDA or AMD DirectML, the diagnostic scanner detects this and logically shifts your engine to an **ungated open-weights repository** (`shuttleai/FLUX.1-schnell`).
- **You do not need to authenticate anything or make an account.**
- Simply ask your agent to `generate a meme` in the UI! Your system will natively download the 16GB weights fully offline during the very first execution automatically.

---

## ⚠️ Common Idiot-Proof Diagnostics

If your terminal throws red text and halts, check these top 3 reasons:

- **Error: Ollama connection refused**
  Your AI's brain is offline! Make sure you physically double-clicked the **Ollama.app** on your computer. If the little llama icon isn't in your menu bar/taskbar, local inference will fail immediately.

- **ModuleNotFoundError: no module named fastmcp**
  You forgot to activate your Virtual Environment. You cannot just launch a fresh terminal and run `python server.py`. You must navigate to the folder and run `source venv/bin/activate` (Mac) or `venv\Scripts\activate` (Windows) first!

- **Invalid JSON: expected value at line 1**
  The Python terminal running the MCP Server is communicating in raw machine code (JSON-RPC). You cannot type plain English into that terminal window! Once it turns on, leave it alone. Open Claude Desktop or Cursor to chat with it.

---

## Technical Architecture (For Developers)

This MCP server exposes your local NFT soul via the [Model Context Protocol](https://modelcontextprotocol.io) standard.

**Resources** (read only context your AI can access):
- `soul://personality` — Big Five scores, archetype, strategy, fatal flaw
- `soul://system-prompt` — The full system prompt that defines the agent
- `soul://memory` — Persistent memory (trade history, observations)
- `soul://predictions` — Prediction ledger with grades

**Core Tools** (35+ functions your AI can call):
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
        "command": "python",
        "args": ["server.py", "--workspace", "/path/to/soul_folder/0420"],
        "cwd": "/path/to/undesirables-mcp-server"
    }
}) as client:
    tools = client.get_tools()
    # 35+ tools now available to any LangChain agent
```

### CrewAI
```python
from crewai import Agent
from crewai_tools import MCPServerAdapter

mcp = MCPServerAdapter(
    command="python",
    args=["server.py", "--workspace", "/path/to/soul_folder/0420"]
)

agent = Agent(
    role="NFT Card Grader",
    tools=mcp.tools,
    goal="Grade trading cards and run Monte Carlo price simulations"
)
```

### OpenAI Agents SDK
```python
from agents import Agent
from agents.mcp import MCPServerStdio

mcp_server = MCPServerStdio(
    command="python",
    args=["server.py", "--workspace", "/path/to/soul_folder/0420"]
)

agent = Agent(
    name="Undesirables Agent",
    instructions="You are an autonomous AI agent with NFT soul personality.",
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
| **433K+ trading cards** | 13 games, 276K actively priced |
| **13.5M+ price observations** | 60+ days of continuous data |
| **On-chain Merkle proofs** | Trustless verification on LiteForge (Chain 4441) |
| **Risk forecast** | Conformal-calibrated VaR/CVaR + Safe-Hold/Momentum grades (Monte Carlo opt-in) |
| **6 MCP tools** | `search_cards`, `get_price_history`, `verify_price`, `oracle_status`, `simulate_price`, `grade_card` |

→ **GitHub**: [litvm-tcg-oracle-mcp](https://github.com/sailorpepe/litvm-tcg-oracle-mcp)  
→ **PyPI**: [litvm-tcg-oracle](https://pypi.org/project/litvm-tcg-oracle/)  
→ **Live Oracle**: [the-undesirables.com/litvm](https://the-undesirables.com/litvm)

---

## The Undesirables Ecosystem

- **Website**: [the-undesirables.com](https://the-undesirables.com)
- **LitVM Oracle**: [the-undesirables.com/litvm](https://the-undesirables.com/litvm)
- **Mint**: [scatter.art/the-undesirables](https://scatter.art/the-undesirables)
- **Docs**: [the-undesirables.com/docs](https://the-undesirables.com/docs)
- **PyPI (MCP)**: [undesirables-mcp-server](https://pypi.org/project/undesirables-mcp-server/) (v1.1.8)
- **PyPI (LitVM)**: [litvm-tcg-oracle](https://pypi.org/project/litvm-tcg-oracle/) (v1.0.3)
- **npm**: [plugin-undesirables](https://npmjs.com/package/plugin-undesirables) (ElizaOS plugin, v2.5.0)
- **Oracle API**: [oracle.the-undesirables.com](https://oracle.the-undesirables.com) (28 endpoints, x402 micropayments)
- **awesome-mcp-servers**: [Listed ✅](https://github.com/punkpeye/awesome-mcp-servers) (85K+ ⭐)
- **Glama**: [Verified ✅ 3.8/5](https://glama.ai/mcp/servers/sailorpepe/undesirables-mcp-server)
- **ElizaOS Plugin**: [Official monorepo](https://github.com/elizaOS/eliza/tree/develop/plugins/plugin-undesirables)
- **x402 Payment Server**: [undesirables-x402-server](https://github.com/sailorpepe/undesirables-x402-server)
- **Kaggle Dataset**: [tcg-market-intelligence](https://www.kaggle.com/datasets/sailorpepe/tcg-market-intelligence)
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

📧 **theundesirables7@gmail.com** · 🐦 **[@undesirables_ai](https://x.com/undesirables_ai)**

© 2026 The Undesirables LLC

---

<div align="center">

⭐ **If this project helped you, please star this repo** — it helps others find it.

[Report Bug](../../issues) · [Request Feature](../../issues)

</div>
