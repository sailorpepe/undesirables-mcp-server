# Skills Registry — Undesirable #1

> **What are skills?** Reusable action templates your agent has learned.
> When you ask your agent to do something it's done before, it loads
> the skill instead of reasoning from scratch. Your agent gets better
> over time as you add more skills.

## How Skills Work

1. **Load**: The agent reads skill files at session start
2. **Match**: When you ask it to do something, it checks if a skill matches
3. **Execute**: If a match is found, it follows the step-by-step workflow
4. **Learn**: You or the agent can add new skills by creating `.md` files here

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

## Installed Skills

| Skill | Trigger | Strategy |
|-------|---------|----------|
| check_portfolio | "check my portfolio" | Universal |
| market_analysis | "what's the market doing" | Universal |
| content_creation | "write a tweet", "promote my NFT" | Universal |
| business_pilot | "set up phone answering", "help with my business" | Universal |
| meme_machine | "make me a meme", "create marketing content" | Universal |
| entry_signal | "is it time to enter" | Structured Trader |
| exit_strategy | "when should I sell" | Structured Trader |
| rebalance_check | "time to rebalance" | Structured Trader |

## Skill Versioning

- Skills are versioned by the holder — you own your agent's learned behaviors
- If you sell your NFT, the new holder gets the default skills (not your custom ones)
- Back up your skills/ directory to keep your agent's learned knowledge
