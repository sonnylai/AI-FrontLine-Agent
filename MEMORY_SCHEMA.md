# Memory Schema — AI FrontLine Agent V2

Defines what data lives where, who writes it, who reads it, and its lifetime.
Use this as the authority before changing AgentState or session_store.

---

## Overview

| Layer | Store | Lifetime | Owned by |
|---|---|---|---|
| Short-term | LangGraph AgentState (in-process RAM) | One request | Orchestrator |
| Session cache | Redis | 4h or session end | Orchestrator node ① |
| Query cache | Redis | 30min – 24h (tiered) | QueryDispatcher |
| Long-term | PostgreSQL + OpenSearch | Permanent | Orchestrator (on session end) |

---

## 1. Short-term Memory — LangGraph AgentState

Lives only in Python memory for the duration of one `/chat` request.
**Discarded when the request completes.** Never written to any database.

### 1a. Request inputs (set by FastAPI before graph starts)

| Field | Type | Example | Notes |
|---|---|---|---|
| `rep_id` | `str` | `"REP-001"` | From JWT |
| `customer_id` | `str` | `"CUST-001"` | From request body |
| `session_id` | `str` | `"REP-001-CUST-001-abc123"` | From request body |
| `message` | `str` | `"lương khách hàng bao nhiêu?"` | Raw user input |
| `conversation_history` | `list[dict]` | `[{role, content}, ...]` | Frontend sends last 10 turns for pronoun resolution. Discarded after IntentRewrite uses it. |

### 1b. Customer 360 — MINIMAL fields only (set by node ①)

**8 fields maximum.** Enough for agents to personalise their prompts and for NBA gap analysis.
Detailed data (transactions, balances, full contract list) is NOT here — QueryDispatcher fetches those on-demand from Hasura.

| Field | Type | Example | Purpose |
|---|---|---|---|
| `customer_id` | `str` | `"CUST-001"` | FK for all downstream queries |
| `full_name` | `str` | `"Đinh Mỹ Yến"` | Personalise agent responses |
| `segment` | `str` | `"Gold"` | NBA rules + product eligibility |
| `kyc_status` | `str` | `"Verified"` | Trust context for agents |
| `income_range` | `str` | `"20-30 triệu VND/tháng"` | Advisory NBA + product eligibility |
| `occupation` | `str` | `"Chuyên viên tài chính"` | Advisory personalisation |
| `city` | `str` | `"Hồ Chí Minh"` | Branch / product availability context |
| `products_held` | `list[str]` | `["BANCASSURANCE", "CASA"]` | NBA gap analysis (codes only, no nested objects) |

**What is NOT in minimal customer_360 (fetched on-demand by QueryDispatcher):**
- Transaction history / aggregations
- Account balances (CASA, savings)
- Loan outstanding balances
- Term deposit details
- Full contract list with clause details
- Credit score, loyalty points (can be added if Advisory needs them — TBD)

### 1c. Long-term summaries (set by node ①, loaded from OpenSearch)

| Field | Type | Notes |
|---|---|---|
| `long_term_summaries` | `list[dict]` | Last 3–5 session summaries. Each: `{session_date, summary, key_concerns, products_discussed, sentiment}`. Injected into IntentRewrite prompt for context. |

### 1d. Routing fields (set by IntentRewriteNode)

| Field | Type | Example | Notes |
|---|---|---|---|
| `sub_questions` | `list[dict]` | See schema below | One entry per agent to invoke. Each item carries its own `intent` field — there is no top-level `intent` in AgentState. |
| `active_agents` | `list[str]` | `["query_dispatcher"]` | Derived from sub_questions for fan-out |
| `rewritten_query` | `str` | `"Chi tiêu của CUST-001 theo danh mục trong 90 ngày gần đây"` | Self-contained query passed to agent |
| `query_type` | `str` | `"aggregate_by_category"` | QueryDispatcher template name (only set when intent = TRANSACTION_QUERY) |
| `query_params` | `dict` | `{date_from: "2026-03-21", date_to: "2026-06-21"}` | Resolved params for QueryDispatcher (dates already concrete, not "3 months ago") |

**sub_questions item schema:**
```json
{
  "id": "sq1",
  "intent": "TRANSACTION_QUERY",
  "agent": "query_dispatcher",
  "query_type": "aggregate_by_category",
  "params": {
    "date_from": "2026-03-21",
    "date_to":   "2026-06-21",
    "category":  null
  },
  "rewritten_query": "Chi tiêu của CUST-001 theo danh mục trong 90 ngày gần đây"
}
```

### 1e. Agent results (appended by each agent in parallel)

| Field | Type | Notes |
|---|---|---|
| `agent_results` | `Annotated[list[AgentResult], operator.add]` | LangGraph reducer — parallel agents each append one entry |

**AgentResult schema:**
```python
{
  "agent":    str,        # "query_dispatcher" | "product" | "contract" | "advisory"
  "answer":   str,        # formatted text answer
  "sources":  list[str],  # e.g. ["hasura:aggregate_by_category"] or ["chunk-id-1"]
  "verified": bool,       # NLI check result
  "warning":  str | None  # NLI warning message if failed
}
```

### 1f. Final output (set by Aggregator)

| Field | Type | Notes |
|---|---|---|
| `final_answer` | `str` | Sonnet-synthesised answer, streamed to client |
| `final_verified` | `bool` | True only if Output Guardrail (Layer 3) AND Final NLI (Layer 4) both pass |
| `final_warning` | `str \| None` | Warning message if either post-stream check fails |

### 1g. Safety flags (set by Input Guardrail)

| Field | Type | Notes |
|---|---|---|
| `input_blocked` | `bool` | True = pipeline short-circuits to `blocked` node |
| `input_block_reason` | `str \| None` | Reason sent to client as SSE error event |

---

## 2. Session Cache — Redis `session:{session_id}`

**Not part of AgentState.** This is what node ① reads from Redis on cache hit.
Contains the assembled context that gets injected into state fields 1b and 1c.

```json
{
  "customer_360": {
    "customer_id":   "CUST-001",
    "full_name":     "Đinh Mỹ Yến",
    "segment":       "Gold",
    "kyc_status":    "Verified",
    "income_range":  "20-30 triệu VND/tháng",
    "occupation":    "Chuyên viên tài chính",
    "city":          "Hồ Chí Minh",
    "products_held": ["BANCASSURANCE", "CASA", "CREDIT_GOLD"]
  },
  "long_term_summaries": [
    {
      "session_date":        "2026-06-10",
      "summary":             "Khách quan tâm đến bảo hiểm nhân thọ banca...",
      "key_concerns":        ["phí hàng năm", "quyền lợi tử vong"],
      "products_discussed":  ["BANCASSURANCE"],
      "sentiment":           "positive"
    }
  ]
}
```

**TTL:** 4h (or cleared on session end)
**Written by:** Orchestrator node ① on cache miss (load from Hasura + OpenSearch)
**Read by:** Orchestrator node ① on cache hit

---

## 3. Query Cache — Redis `query:{customer_id}:{query_type}:{params_hash}`

QueryDispatcher writes here after each Hasura call. Next identical query is served from cache.

| query_type | TTL | Rationale |
|---|---|---|
| `profile_demographics` | 24h | Demographics rarely change within a day |
| `product_portfolio_summary` | 24h | Products change infrequently (same TTL as demographics) |
| `loan_balance_remaining` | 6h | Updated by payment cycle, not real-time |
| `term_deposit_list` | 6h | Stable within a day |
| `insurance_contract_status` | 6h | Stable within a day |
| `segment_gap_analysis` | 6h | Derived from portfolio, same TTL |
| `aggregate_by_category` | 30min | New transactions arrive frequently |
| `aggregate_by_merchant` | 30min | New transactions arrive frequently |
| `transaction_count_by_period` | 30min | New transactions arrive frequently |
| `casa_balance_summary` | 30min | Balance changes on every transaction |

---

## 4. Long-term Memory — PostgreSQL + OpenSearch

Written once per session on `POST /sessions/end`. Read once per session on node ① cache miss.

### 4a. Conversation Summaries — OpenSearch index `conversation-summaries`

Written by Haiku summarisation on session end.

| Field | Type | Notes |
|---|---|---|
| `session_id` | `str` | Document ID (MD5 hash of session_id) |
| `customer_id` | `str` | Filter key for retrieval |
| `session_date` | `str` | `YYYY-MM-DD` |
| `summary` | `str` | 2–4 sentence narrative of the session |
| `key_concerns` | `list[str]` | Topics the customer raised or showed interest in |
| `products_discussed` | `list[str]` | Product codes mentioned |
| `sentiment` | `str` | `positive` \| `neutral` \| `hesitant` \| `negative` |

**Read:** Last 3–5 entries (sorted by session_date desc) loaded into `long_term_summaries` at session start.

### 4b. Behavior Profile — PostgreSQL table `customer_behavior_profiles`

*(Not yet implemented — Phase 4+ scope)*

| Field | Type | Notes |
|---|---|---|
| `customer_id` | `str` | PK |
| `communication_style` | `str` | e.g. "detail-oriented", "big-picture" |
| `call_preferences` | `str` | e.g. "prefers morning calls" |
| `objection_patterns` | `list[str]` | Common objections raised |
| `updated_at` | `timestamp` | |

### 4c. Product Offer History — PostgreSQL table `product_offer_history`

*(Not yet implemented — Phase 4+ scope)*

| Field | Type | Notes |
|---|---|---|
| `customer_id` | `str` | |
| `product_code` | `str` | e.g. `"BANCASSURANCE"` |
| `offered_date` | `date` | |
| `outcome` | `str` | `accepted` \| `rejected` \| `pending` |
| `rep_id` | `str` | Which rep made the offer |

---

## 5. What is NOT duplicated (overlap check)

| Data | Only in |
|---|---|
| Transaction details / aggregations | QueryDispatcher → Hasura (never in state) |
| Account balances | QueryDispatcher → Hasura (never in state) |
| Full contract list + clauses | ContractAgent → Neo4j + Redis `contract:{id}` (never in state) |
| Product T&Cs / rates | ProductAgent → OpenSearch RAG (never in state) |
| Conversation turns (current session) | `conversation_history` in state (frontend-owned, discarded after IntentRewrite) |
| Conversation summaries (past sessions) | `long_term_summaries` in state (read-only, from OpenSearch) |
| Customer demographics (name, segment…) | `customer_360` in state (8 fields only) AND Redis session cache (same 8 fields, serialised) |

> **Note:** `customer_360` in state and the Redis session cache hold the same 8 fields. This is intentional — Redis is the source, state is the in-process copy for that request. No business logic duplication.

---

## 6. QueryDispatcher Template Reference

| `query_type` | Hasura query fields | Key params |
|---|---|---|
| `profile_demographics` | `income_range, occupation, kyc_status, credit_score, loyalty_points, city, relationship_since` | none |
| `product_portfolio_summary` | `products_held{product_code}, contracts{contract_id, product_name, status, start_date, end_date}` | none |
| `aggregate_by_category` | `SUM(amount) GROUP BY merchant_category` | `date_from`, `date_to` |
| `aggregate_by_merchant` | Raw transactions → Python aggregation. Two sub-queries: `AggMerchantByName` (`merchant_name _ilike`) when `merchant_name` param present; `AggMerchantByCat` (`merchant_category _eq`) otherwise. | `date_from`, `date_to`, `merchant_name` **or** `merchant_category` |
| `transaction_count_by_period` | `COUNT(*) WHERE transaction_date BETWEEN` | `date_from`, `date_to` |
| `casa_balance_summary` | `accounts{account_type, balance, currency}` WHERE type IN CASA/SAVINGS | none |
| `loan_balance_remaining` | `loan_accounts{product_name, outstanding_balance, monthly_installment, maturity_date}` | none |
| `term_deposit_list` | `term_deposits{product_name, principal_amount, interest_rate, maturity_date, status}` | none |
| `insurance_contract_status` | `contracts{product_type=INSURANCE, status, start_date, end_date, key_amount}` | none |
| `segment_gap_analysis` | No Hasura call — pure Python `_fmt_segment_gap(customer_360)` using `products_held` already in state | none |
