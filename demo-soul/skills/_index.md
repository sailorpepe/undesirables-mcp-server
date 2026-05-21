# Skills Registry — Undesirable #1

> **What are skills?** Reusable action templates your agent has learned.
> When you ask your agent to do something it's done before, it loads
> the skill instead of reasoning from scratch. Your agent gets better
> over time as you add more skills.

## How Skills Work

1. **Load**: The agent reads skill files at session start
2. **Match**: When you ask it to do something, it checks if a skill matches
3. **Execute**: If a match is found, it follows the step-by-step workflow
4. **Data**: Financial skills fetch live data from DeFiLlama and Etherscan before responding
5. **Learn**: You or the agent can add new skills by creating `.md` files here

## Adding Custom Skills

Create a new `.md` file in this directory with this format:

```markdown
# Skill: [Name]
Trigger: [When to use this skill]
Context: [What the agent needs to know]
Steps:
1. [Step 1]
2. [Step 2]
Output: [Expected result format]
```

## Installed Skills (16)

### Content & Creative (5)
| Skill | Trigger | Data Source |
|-------|---------|------------|
| content_creation | "write a tweet", "promote my NFT" | LLM generation |
| image_generation | "generate an image", "create art" | MCP image tools |
| music_generation | "make a beat", "create a song" | ACE-Step model |
| meme_machine | "make me a meme", "marketing content" | PIL + templates |
| business_pilot | "set up phone answering", "help with business" | 23-module system |

### Market Intelligence (6) — Live Data
| Skill | Trigger | Data Source |
|-------|---------|------------|
| market_analysis | "what's the market doing" | Oracle API (370K products) |
| entry_signal | "is it time to enter", "buy signal" | DeFiLlama prices |
| exit_strategy | "when should I sell", "take profit" | DeFiLlama prices |
| conviction_score | "should I buy", "score this idea" | DeFiLlama prices |
| farm_yield | "find best yield", "where should I farm" | DeFiLlama yields |
| risk_assessment | "is this safe", "risk check" | DeFiLlama protocol TVL |

### Portfolio & On-Chain (4) — Live Data
| Skill | Trigger | Data Source |
|-------|---------|------------|
| check_portfolio | "check my portfolio", "what's my balance" | Etherscan V2 |
| whale_tracker | "whale watch", "smart money" | Etherscan V2 |
| rebalance_check | "time to rebalance", "portfolio drift" | Etherscan V2 |
| compound_strategy | "compound my rewards", "should I reinvest" | DeFiLlama yields |

### Logging (1)
| Skill | Trigger | Data Source |
|-------|---------|------------|
| prediction_log | "log this prediction" | PREDICTIONS_LEDGER.json |

## Data Sources

- **DeFiLlama** — Free, no API key. Provides yield pool APYs, protocol TVL, and token prices.
- **Etherscan V2** — Free API key. Provides on-chain wallet balances and transaction history.
- **Oracle API** — Free endpoints at oracle.the-undesirables.com for TCG market data.

## Skill Versioning

- Skills are versioned by the holder — you own your agent's learned behaviors
- If you sell your NFT, the new holder gets the default skills (not your custom ones)
- Back up your skills/ directory to keep your agent's learned knowledge
