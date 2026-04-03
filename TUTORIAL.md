# How to Port Your Autonomous Soul Into ElizaOS

> Turn your Undesirable NFT into a fully autonomous ElizaOS agent — running on Discord, Twitter, or any platform.

## What You'll Get

By the end of this tutorial, your Undesirable soul will be running as a full ElizaOS agent with:
- 🧠 Unique personality (archetype, Big Five, speech style)
- 📊 23 skills (market analysis, Business Pilot, Meme Machine, etc.)
- 💰 Free local inference via Ollama (no API costs)
- 🐦 Discord + Twitter deployment ready

## Prerequisites

- [Node.js 20+](https://nodejs.org)
- [Ollama](https://ollama.com) installed and running
- Your Undesirable soul workspace (downloaded from [the-undesirables.com/soul](https://the-undesirables.com/soul))

---

## Step 1: Install Ollama + Download a Model

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (llama3.1 recommended)
ollama pull llama3.1:8b

# Verify it's running
ollama list
```

## Step 2: Install ElizaOS

```bash
# Install the ElizaOS CLI
npm install -g elizaos

# Verify installation
elizaos --version
```

## Step 3: Download Your Soul Workspace

1. Go to [the-undesirables.com/soul](https://the-undesirables.com/soul)
2. Connect your wallet
3. Enter your token ID
4. Click **Download Workspace**
5. Unzip the folder

Your workspace contains:
```
soul-workspace/
├── SOUL.md              # Your personality profile
├── SYSTEM_PROMPT.txt    # System instructions
├── MEMORY.md            # Persistent memory
├── PREDICTIONS_LEDGER.json
└── skills/              # 23 skill files
    ├── market_analysis.md
    ├── business_pilot.md
    ├── meme_machine.md
    ├── content_creation.md
    └── ... (12 more)
```

## Step 4: Convert Your Soul to character.json

```bash
# Clone the converter tool
git clone https://github.com/sailorpepe/undesirables-mcp-server.git
cd undesirables-mcp-server

# Convert your soul (replace with your token ID)
node soul-to-eliza.js --workspace /path/to/your/soul-workspace

# Output: characters/undesirable_XXXX.character.json
```

This converts your SOUL.md into ElizaOS format with:
- Name, archetype, and strategy
- Adjectives from your personality profile
- Bio extracted from your backstory
- Message examples matching your speech style
- All 23 skills as topics
- Ollama as the default model provider (free!)

## Step 5: Install the Undesirables Plugin

```bash
# Option A: From npm (recommended)
elizaos plugins add plugin-undesirables

# Option B: Manual install
npm install plugin-undesirables
```

## Step 6: Configure Your Agent

Edit your `character.json` to add the plugin and workspace path:

```json
{
  "name": "Your Undesirable Name",
  "plugins": ["plugin-undesirables"],
  "settings": {
    "UNDESIRABLES_WORKSPACE": "/path/to/your/soul-workspace"
  },
  "modelProvider": "ollama",
  "settings": {
    "model": "llama3.1:8b"
  }
}
```

Or set the environment variable:
```bash
export UNDESIRABLES_WORKSPACE=/path/to/your/soul-workspace
```

## Step 7: Launch Your Agent

```bash
# Start ElizaOS with your character
elizaos start --character ./characters/undesirable_0420.character.json
```

Your Undesirable is now live! It will respond in character using its unique personality, with access to all 23 skills.

## Step 8: Deploy to Discord or Twitter

### Discord
```bash
# Add your Discord bot token to .env
echo "DISCORD_BOT_TOKEN=your_token_here" >> .env

# Update character.json
# "clients": ["discord"]
```

### Twitter/X
```bash
# Add Twitter credentials to .env
echo "TWITTER_USERNAME=your_bot_username" >> .env
echo "TWITTER_PASSWORD=your_bot_password" >> .env

# Update character.json
# "clients": ["twitter"]
```

---

## MCP Server (Alternative)

If you prefer using MCP instead of ElizaOS, you can run the MCP server directly:

```bash
cd undesirables-mcp-server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run with your token
python server.py --workspace /path/to/your/soul-workspace
```

This exposes your soul via the Model Context Protocol, compatible with:
- **Cursor** — Add to `.cursor/mcp.json`
- **Claude Desktop** — Add to `claude_desktop_config.json`
- **VS Code** — Via MCP extension
- **Any MCP client** — Standard JSON-RPC

---

## Architecture

```
┌─────────────────────────────────┐
│     ElizaOS Agent Runtime       │
│  ┌───────────────────────────┐  │
│  │ plugin-undesirables       │  │
│  │  • soulProvider           │  │
│  │  • MARKET_ANALYSIS        │  │
│  │  • BUSINESS_PILOT         │  │
│  │  • MEME_MACHINE           │  │
│  │  • LOAD_SKILL (23 total)  │  │
│  └────────────┬──────────────┘  │
│               │                 │
│  ┌────────────▼──────────────┐  │
│  │ Soul Workspace (local)    │  │
│  │  SOUL.md + MEMORY.md      │  │
│  │  + 23 skills              │  │
│  └────────────┬──────────────┘  │
└───────────────┼─────────────────┘
                │
   ┌────────────▼──────────────┐
   │    Ollama (local LLM)     │
   │    llama3.1:8b            │
   │    FREE — no API costs    │
   └───────────────────────────┘
```

## Links

- **Mint**: [scatter.art/the-undesirables](https://scatter.art/the-undesirables)
- **Website**: [the-undesirables.com](https://the-undesirables.com)
- **MCP Server**: [github.com/sailorpepe/undesirables-mcp-server](https://github.com/sailorpepe/undesirables-mcp-server)
- **ElizaOS Plugin**: [github.com/sailorpepe/plugin-undesirables](https://github.com/sailorpepe/plugin-undesirables)
- **Docs**: [the-undesirables.com/docs](https://the-undesirables.com/docs)

---

**The Undesirables** — 4,444 autonomous AI agents on Ethereum. EST. 2026 🐸
