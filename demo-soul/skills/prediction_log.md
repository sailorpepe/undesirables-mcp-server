# Skill: Log Market Prediction

**Trigger:** "log this prediction", "record conviction score", "add to ledger"
**Context:** Structures trade ideas for the Reflexion system to evaluate later
**Personality:** Student The Contrarian

## Steps

1. Parse the conviction score JSON
2. Identify the target asset and timeline
3. Format as a strict ledger entry
4. Wait for user to confirm saving to PREDICTIONS_LEDGER.json
5. Output the prediction block

## Expected Output

```json
{
  "id": "PRED-[generate_random_4_digits]",
  "timestamp": "[current_iso_time]",
  "asset": "[target_asset]",
  "direction": "[LONG/SHORT/YIELD_FARM]",
  "timeframe": "7d",
  "entry_price": [current_price],
  "target_price": [target_price],
  "conviction": [total_conviction_score],
  "reasoning": "[1-2 sentence core thesis]"
}
```
