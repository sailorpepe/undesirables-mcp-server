# Skill: Whale Tracker

**Trigger:** "whale", "smart money", "whale watch", "what are whales buying"
**Context:** Track large wallet movements and institutional flows on Ethereum
**Personality:** Student The Contrarian — Discipline 70%, observational

## Data Source

Live on-chain data from Etherscan V2 API. Tracks recent ETH transfers from known whale addresses.

## Steps

1. If user provides a wallet address (0x...), track that specific wallet
2. Otherwise, monitor default whale wallets (large known holders)
3. Show the 5 most recent transactions with direction (IN/OUT), amount, and date
4. Analyze the pattern — accumulation, distribution, or neutral?
5. Deliver verdict in character voice

## Output Format

```
🐋 Whale Watch Report
Wallet: 0xd8dA...6045
Recent Activity:
• [2026-05-21] OUT 50.0000 ETH — 0x1234abcd...
• [2026-05-20] IN 100.0000 ETH — 0x5678efgh...
Pattern: ACCUMULATION / DISTRIBUTION / NEUTRAL
Conviction: [LOW/MED/HIGH]
```

## Disclaimer

⚠️ This uses real on-chain data but is AI-interpreted. Not financial advice. Always DYOR.
