# Skill: Rebalance Check

**Trigger:** "time to rebalance", "portfolio drift", "rebalance"
**Context:** Evaluates whether portfolio has drifted from target allocation
**Personality:** Rebalance frequency: Bi-weekly

## Steps

1. Query current portfolio allocation
2. Compare against target (equal weight across approved protocols)
3. Calculate drift: any position > 13% is overweight
4. If drift > 5%: recommend rebalance trades
5. Execute or log recommendation

## Rebalance Rules

- Frequency: Bi-weekly
- Only rebalance if gas is reasonable (<$10 per tx)
- Min drift to trigger: 5% deviation from target
- Max trades per rebalance: 4
