# Skill: Farm Yield

**Trigger:** "find best yield", "where should I farm", "yield opportunities"
**Context:** Scans approved lending/staking protocols for optimal APY
**Personality:** Low-Key The Strategist (The Strategist) — Risk 15%, Patience 100%

## Steps

1. Query approved protocols: lending, liquid staking, yield aggregators
2. Rank by risk-adjusted APY (not raw APY)
3. Filter through risk tolerance (15%):
   - Only established pools >$50M TVL
4. Check current positions against max position size (9%)
5. Recommend allocation with rationale
6. 

## Output Format

```
🌾 Yield Opportunities
1. [Protocol] — [Pool] — [APY]% — TVL: $[X]M — Risk: [LOW/MED/HIGH]
2. ...
Recommendation: [action] based on your Yield Optimizer strategy
```
