# Skill: Generate Conviction Score

**Trigger:** "should I buy", "what do you think of [asset]", "score this idea"
**Context:** Forces the agent into a structured quantitative framework
**Personality:** Student The Contrarian — Minimum Conviction: 74%

## Steps

1. Analyze technicals (RSI, MACD, Volume) for [asset]
2. Analyze on-chain metrics (Flows, Activity)
3. Analyze sentiment & funding rates
4. Run strategy alignment check (Structured Trader)
5. Check against fatal flaw bias (Money printer mentality)
6. Calculate totals and apply disposition penalty (-0%)
7. Tally final score
8. Output pure JSON format

## Expected Output

Produce ONLY the following JSON block:
```json
{
  "technical_score": [0-100],
  "onchain_score": [0-100],
  "sentiment_score": [0-100],
  "strategy_alignment": [0-100],
  "fatal_flaw_check": "[CLEAR or WARNING]",
  "total_conviction": [weighted average minus penalty],
  "action": "[STRONG_BUY / BUY / WATCH / HOLD / SELL / STRONG_SELL]"
}
```
