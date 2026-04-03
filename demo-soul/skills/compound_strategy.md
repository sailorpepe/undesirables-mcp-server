# Skill: Compound Strategy

**Trigger:** "compound my rewards", "should I reinvest", "harvest and compound"
**Context:** Evaluates whether to harvest and reinvest yield farming rewards
**Personality:** Patience 100% — Hold target: 90 days

## Steps

1. Check accumulated rewards across all positions
2. Calculate gas cost vs reward value (only compound if reward > 3x gas)
3. Evaluate compound timing: Wait for gas dips — patience is high
4. Execute compound or recommend waiting
5. Log to MEMORY.md → Trade History

## Decision Matrix

| Reward Value | Gas Cost | Action |
|-------------|----------|--------|
| > 10x gas | Any | Compound immediately |
| 3-10x gas | Low (<$5) | Compound |
| 3-10x gas | High | Wait for gas dip |
| < 3x gas | Any | Wait and accumulate |
