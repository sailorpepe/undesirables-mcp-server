# MEMORY: Undesirable #1

> **Architecture**: MemGPT-inspired tiered memory system.
> This file is maintained locally by the holder — never uploaded to Arweave.
> The agent reads this file at session start to maintain continuity.
> The agent can autonomously update its own memory using the tools below.

## Tier 1: Core Memory (Always Loaded)

> Small, fixed block of data perpetually visible in the active context window.
> This is initialized from SOUL.md and should contain the most important
> information the agent needs to function.

### About Me
<!-- The agent's self-knowledge — auto-populated from SOUL.md -->
<!-- Can be updated by the agent using core_memory_replace -->

### About Holder
<!-- Facts about the holder — learned through conversation -->
<!-- Example: "Holder prefers conservative DeFi strategies" -->
<!-- Example: "Holder's timezone is CST" -->

## Tier 2: Recall Memory (Session Overflow)

> Searchable persistence of session history. When conversation overflows
> the context window, older messages are summarized and stored here.
> The agent can search this tier to recall past interactions.

### Session Log
<!-- Auto-generated summaries of past sessions -->
<!-- Format: [DATE] — [SUMMARY] — [KEY DECISIONS] -->

### Conversation Index
<!-- Keywords and topics from past conversations for semantic search -->
<!-- Format: [TOPIC] — [SESSION_DATE] — [KEY_INSIGHT] -->

## Tier 3: Archival Memory (Long-Term Storage)

> Long-term vector database. The agent autonomously decides when to
> save an insight and when to retrieve it via semantic search.
> This tier gives the agent "learned wisdom" that accumulates over time.

### Trade History
<!-- Tracked automatically by the orchestration layer -->
<!-- Format: [DATE] [ACTION] [ASSET] [AMOUNT] [PROTOCOL] [RATIONALE] [OUTCOME] -->

### Predictions Ledger
<!-- See PREDICTIONS_LEDGER.json for the full structured log and self-calibration -->
<!-- Format: [DATE] [PREDICTION_ID] [OUTCOME] [REFLECTION] -->

### Market Insights
<!-- Patterns and correlations the agent has discovered -->
<!-- Format: [DATE] — [INSIGHT] — [CONFIDENCE] -->

### Relationships
<!-- Other agents and users this entity has interacted with -->
<!-- Format: [AGENT_ID/USER_ID] — [RELATIONSHIP_NOTES] — [TRUST_LEVEL] -->

### Durable Facts
<!-- Facts the agent should remember permanently -->
<!-- These survive all session resets -->

## Memory Tools (for runtime integration)

```
Available memory operations:
• core_memory_append(key, value) — Add to Core Memory
• core_memory_replace(key, old, new) — Update Core Memory
• recall_search(query) — Search Recall Memory
• archival_insert(content) — Save to Archival Memory
• archival_search(query) — Search Archival Memory
```
