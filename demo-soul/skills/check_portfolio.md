# Skill: Check Portfolio

**Trigger:** "check my portfolio", "what's my balance", "how am I doing"
**Context:** Reads TBA wallet state via on-chain query
**Personality:** Student The Contrarian (The Contrarian) — Structured Trader

## Steps

1. Query TBA address for current ETH and token balances
2. Calculate total portfolio value in ETH and USD
3. Compare against last known state from MEMORY.md
4. Flag any positions that violate guardrails:
   - Max position size: 13%
   - Max drawdown: 30%
5. Report in character voice

## Output Format

```
Portfolio Status — Undesirable #1
Total Value: [X] ETH ($[Y])
Positions: [list]
Health: [OK / WARNING / CRITICAL]
Last Rebalance: [date]
```

## Memory Update

After checking, update MEMORY.md → Archival Memory → Trade History with:
- [DATE] PORTFOLIO_CHECK [TOTAL_VALUE] [HEALTH_STATUS]
