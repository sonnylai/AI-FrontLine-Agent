# AI FrontLine Agent — System Architecture

## Overview

AI FrontLine Agent is a bank CRM AI system that gives sales representatives an AI-powered assistant to help them understand customers, query data, and generate sales recommendations. The UI has two panels: a **chat panel (left)** where the rep interacts with the AI agent, and a **customer 360 panel (right)** showing structured customer information loaded at session start.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | HTML + Vanilla JS | Two-panel UI: chat + customer 360 |
| Backend | Python / FastAPI | Thin HTTP layer: auth, SSE streaming, request validation only |
| Agent Framework | LangGraph | Multi-agent orchestration, state management, conditional routing |
| GraphQL API | Hasura | Auto-generated GraphQL over PostgreSQL; row-level security for rep portfolio access |
| LLM (Reasoning) | Claude Sonnet 4.6 — Anthropic API | Contract reasoning, product knowledge, advisory, final synthesis |
| LLM (Routing) | Claude Haiku 4.5 — Anthropic API | Intent classification + query rewrite (single call, fast) |
| LLM (NLI) | Claude Haiku 4.5 — Anthropic API | Final NLI faithfulness check (cost-efficient) |
| Embedding | Cohere embed-multilingual-v3 — Cohere API | Document and query embedding (Vietnamese + English) |
| Structured DB | PostgreSQL | Customer 360 data, transactions, products, long-term memory |
| Vector DB | OpenSearch | Product documents, contract clauses, RAG retrieval, conversation summaries |
| Graph DB | Neo4j | Customer contract entity relationships |
| Cache | Redis | Session context, query results, contract data, RAG results |
| Observability | LangSmith | Tracing, prompt versioning, RAGAS evaluation scores |
| Data Source | Data Lake | Source of truth feeding all downstream databases |

---

## System Components

### 1. Frontend — HTML + Vanilla JS

Two-panel layout served as a static page:

- **Left — Chat Panel:** Rep types natural language questions. Responses stream token-by-token via the browser's native `EventSource` API (SSE). A verified (`✓`) or warning (`⚠`) indicator appears after the async post-stream checks complete.
- **Right — Customer 360 Panel:** Loaded at session start via `GET /api/customers/{id}`. Displays customer name, demographics, KYC status, credit score, segment, product portfolio (CASA, loans, term deposits, credit cards, bancassurance contracts), recent transaction summary, open support cases, and insurance contract dates.

---

### 2. Backend — FastAPI (Thin HTTP Layer)

FastAPI is a **thin HTTP layer only** — it does not load memory, assemble context, or execute business logic. All of that belongs to the Orchestrator.

**Key endpoints:**

| Endpoint | What FastAPI Does | What Happens Next |
|---|---|---|
| `POST /api/sessions/start` | Validate JWT, generate `session_id`, return it | Orchestrator initializes on first `/chat/stream` call |
| `POST /api/sessions/end` | Validate JWT, forward `session_id` to Orchestrator | Orchestrator summarizes + writes long-term memory |
| `POST /api/chat/stream` | Validate JWT + Pydantic envelope, invoke Orchestrator | Returns SSE token stream |
| `GET /api/customers/{id}` | Validate JWT + portfolio access, query Hasura | Customer 360 JSON for right panel |
| `GET /api/health` | Liveness check | — |

**Pydantic** validates the structured request envelope (`session_id`, `customer_id`, `message`). The NL message content itself is not validated — it flows to the Orchestrator as-is.

---

### 3. Authentication & Authorization

- JWT validation on every request as FastAPI middleware — runs before the Orchestrator is reached
- A sales rep can only access customers in their assigned portfolio
- Portfolio access enforced at two points: FastAPI middleware (customer 360 endpoint) and Hasura row-level permissions (all GraphQL queries)

---

### 4. GraphQL API — Hasura

Hasura sits between the QueryDispatcher and PostgreSQL. It auto-generates a GraphQL API from the PostgreSQL schema and enforces row-level security.

**Why Hasura over raw SQL or a custom GraphQL server:**
- Row-level permission rules map directly to rep portfolio access — no custom auth code needed
- QueryDispatcher uses pre-built named query templates; Hasura handles query execution and connection pooling
- Admin console for schema inspection without writing boilerplate

**Permission model:** Every GraphQL query from the QueryDispatcher carries the rep's JWT. Hasura validates it and applies the row filter `WHERE rep_id = JWT.sub` transparently before hitting PostgreSQL.

---

### 5. Orchestrator — LangGraph StateGraph

The Orchestrator **is** the LangGraph `StateGraph` — a Python execution controller with **no LLM calls of its own**. It is not an agent. It:

- Owns session initialization: loads long-term memory and assembles the system prompt on first message
- Manages the LangGraph node execution order
- Handles conditional routing (single intent → direct, multi-intent → fan-out)
- Collects sub-agent outputs and drives final synthesis
- Pipes the async token generator back to FastAPI as SSE

**Mental model:**

| Thing | Role | Makes LLM calls? |
|---|---|---|
| Orchestrator | Traffic controller — routes, coordinates, pipes tokens | No |
| IntentRewriteNode | Chef — classifies and rewrites | Yes (Haiku) |
| Knowledge Agents | Chefs — retrieve and reason | Yes (Sonnet) |
| QueryDispatcher | Cashier — maps to template, executes deterministically | No |

---

### 6. Agent Pipeline — LangGraph Nodes

```mermaid
flowchart TD
    FE["Frontend\nChat Panel · SSE EventSource"]
    API["FastAPI\n/chat/stream"]

    subgraph ORCH["Orchestrator — LangGraph StateGraph  (Python controller, no LLM)"]
        RC["① Load Session Context\nfrom Redis  ·  on miss: load from Postgres + OpenSearch"]
        IG["② Input Guardrail  ·  sync  ·  200ms\nPII masking · prompt injection · topic filter"]
        IR["③ IntentRewriteNode  ·  Haiku 4.5\nClassify + Rewrite + Split into sub-questions"]
        ROUTE{"④ Conditional Router\nsingle intent → direct to 1 agent\nmulti-intent → fan-out to N agents"}

        QD["QueryDispatcher\nNo LLM · Hasura GraphQL → Postgres"]
        CKA["ContractKnowledgeAgent\nSonnet 4.6 · Graph DB + RAG"]
        PKA["ProductKnowledgeAgent\nSonnet 4.6 · RAG only"]
        AA["AdvisoryAgent\nSonnet 4.6 · Profile + NBA"]

        NQ["NLI ✓  per-answer  sync  Haiku"]
        NC["NLI ✓  per-answer  sync  Haiku"]
        NP["NLI ✓  per-answer  sync  Haiku"]
        NA["NLI ✓  per-answer  sync  Haiku"]

        AGG["⑤ AggregatorNode\nMerge verified + flagged answers"]
        SYN["⑥ Final Synthesis  ·  Sonnet 4.6\nStream tokens to client"]
        OG["Output Guardrail  ·  async post-stream\nPII · compliance · security"]
        FN["Final NLI  ·  async post-stream\nSynthesis faithfulness check  ·  Haiku"]
    end

    REDIS[("Redis\nSession · RAG cache · Query cache")]
    PG[("PostgreSQL\nCustomer 360")]
    HASURA["Hasura\nGraphQL API"]
    NEO[("Neo4j\nContract graph")]
    OS[("OpenSearch\nProduct + Contract docs")]

    FE -->|"POST message"| API
    API -->|"SSE token stream + verdict event"| FE

    API --> RC
    RC <-->|"session:{rep}:{cust}"| REDIS
    RC --> IG
    IG --> IR
    IR --> ROUTE

    ROUTE -->|"TRANSACTION_QUERY"| QD
    ROUTE -->|"CONTRACT_QUERY"| CKA
    ROUTE -->|"PRODUCT_KNOWLEDGE"| PKA
    ROUTE -->|"ADVISORY"| AA

    QD --> HASURA --> PG
    QD --> NQ

    CKA <-->|"traverse relationships"| NEO
    CKA <-->|"BM25 30% + semantic 70%\ntop-10 + top-10 → RRF → cross-encoder → top-5"| OS
    CKA --> NC

    PKA <-->|"BM25 30% + semantic 70%\ntop-10 + top-10 → RRF → cross-encoder → top-5"| OS
    PKA --> NP

    AA --> NA

    NQ --> AGG
    NC --> AGG
    NP --> AGG
    NA --> AGG

    AGG --> SYN
    SYN -->|"token stream"| API
    SYN --> OG
    SYN --> FN
    OG -->|"verified ✓ / warning ⚠ SSE event"| API
    FN -->|"verified ✓ / warning ⚠ SSE event"| API
```

---

#### Node 1: IntentRewriteNode (Haiku 4.5)

A **single LLM call** that performs both classification and rewriting simultaneously.

**Jobs:**
1. **Intent Classification** — detect which agent categories apply: `TRANSACTION_QUERY`, `CONTRACT_QUERY`, `PRODUCT_KNOWLEDGE`, `ADVISORY`
2. **Query Rewrite** — resolve vague references ("this customer" → `CUST_001`, "last 3 months" → date range), split multi-intent questions into atomic sub-questions, each routable to exactly one agent

**Output (list of sub-questions):**
```json
[
  {
    "id": "sq1",
    "intent": "TRANSACTION_QUERY",
    "agent": "QueryDispatcher",
    "query_type": "aggregate_by_merchant",
    "params": {
      "customer_id": "CUST_001",
      "merchant_category": "GRAB",
      "date_from": "2026-03-20",
      "date_to": "2026-06-20",
      "aggregation": "SUM_AMOUNT"
    }
  }
]
```

If the list has 1 item → Conditional Router sends directly to that agent. If multiple items → fan-out in parallel.

---

#### Node 2: Conditional Router

Pure Python LangGraph edge. Reads the sub-question list from IntentRewriteNode:

- `len == 1` → route directly to the single matched agent (no fan-out overhead)
- `len > 1` → spawn parallel branches, one per sub-question

This avoids unnecessary parallel overhead for the majority of single-intent messages (estimated ~70% of queries).

---

#### Node 3: QueryDispatcher — No LLM

Handles all `TRANSACTION_QUERY` and structured profile queries. Pure Python — no LLM involved.

Maps `query_type` to a pre-built named GraphQL query, executes it via Hasura against PostgreSQL. Result: < 100ms on cache hit, eliminates hallucination risk on structured data retrieval.

**Predefined query templates (MVP):**
- `aggregate_by_merchant`
- `aggregate_by_category`
- `product_portfolio_summary`
- `loan_balance_remaining`
- `segment_gap_analysis`
- `transaction_count_by_period`
- `casa_balance_summary`
- `term_deposit_list`
- `insurance_contract_status`

If no template matches (~20% of cases), falls back to **NL2SQL** — Haiku generates SQL, validated as `SELECT`-only via `EXPLAIN` before execution.

Result → per-answer NLI check (Haiku) → Aggregator.

---

#### Node 4: ContractKnowledgeAgent (Sonnet 4.6)

Handles `CONTRACT_QUERY` — questions requiring reasoning over the customer's signed contracts.

**Steps:**
1. Check Redis for cached contract data (`contract:{customer_id}`, TTL 12h)
2. On miss: traverse Neo4j — `Customer -[HAS]-> Contract -[IS_TYPE]-> Policy -[HAS_CLAUSE]-> Clause`
3. Write Graph DB result to Redis cache
4. Check Redis semantic cache for RAG result (`rag:{query_hash}`)
5. On miss: hybrid RAG on OpenSearch — BM25 (30%) + semantic (70%) → top-10 each → RRF merge → cross-encoder re-rank → **top-5 clause chunks**
6. Write RAG result to Redis cache
7. Send contract graph context + top-5 chunks to Sonnet for reasoning
8. Per-answer NLI check (Haiku): answer vs retrieved chunks → return to Aggregator

**Data boundary:**
- **Neo4j:** contract metadata and entity relationships (contract ID, type, status, parties, clause references)
- **OpenSearch:** full clause text and policy documents (linked to Neo4j nodes by `contract_id`)

---

#### Node 5: ProductKnowledgeAgent (Sonnet 4.6)

Handles `PRODUCT_KNOWLEDGE` — general product information queries (T&Cs, rates, promotions, eligibility).

**Steps:**
1. Check Redis semantic cache for RAG result (`rag:{query_hash}`, TTL 6h)
2. On miss: hybrid RAG on OpenSearch — BM25 (30%) + semantic (70%) → top-10 each → RRF merge → cross-encoder re-rank → **top-5 chunks**
3. Write RAG result to Redis cache
4. Send top-5 chunks to Sonnet for reasoning
5. Per-answer NLI check (Haiku): answer vs retrieved chunks → return to Aggregator

**Why 30/70 BM25/semantic split for Vietnamese:** BM25 does exact token matching — Vietnamese compound words and tone marks cause tokenization mismatches. Semantic embedding handles morphological variation naturally. BM25 at 30% still handles exact product codes, clause numbers, and English terms embedded in Vietnamese text (e.g., "KYC", "APE", "L/C").

---

#### Node 6: AdvisoryAgent (Sonnet 4.6)

Handles `ADVISORY` — sales script generation and product recommendations.

Uses customer profile (from session context), transaction behavior, conversation history, and NBA/NBO model output as context. Generates tailored talking points and sales scripts grounded in actual customer data.

Per-answer NLI check (Haiku) ensures the script does not reference facts not present in the customer's profile or conversation history.

*Note: TCB NBA/NBO model integration is simplified for MVP — uses rule-based scoring on segment gap and product portfolio gaps.*

---

#### Node 7: AggregatorNode

Collects all validated sub-answers from all branches. If a sub-answer failed NLI, it is included with an uncertainty flag rather than dropped — the Aggregator tells Sonnet which answers are verified and which are uncertain. Merges everything into one context block for final synthesis.

---

#### Node 8: Final Synthesis (Sonnet 4.6)

Receives the merged context block from the Aggregator. Generates a single cohesive, natural language response in Vietnamese. Streams tokens via FastAPI async generator → SSE to frontend.

---

#### Node 9: Safety Checks — 4 Layers

| # | Check | Model | Timing | Purpose |
|---|---|---|---|---|
| 1 | **Input Guardrail** | Rule-based | Sync, pre-pipeline, 200ms | Prompt injection, PII masking in query, off-topic filter |
| 2 | **Per-agent NLI** | Haiku 4.5 | Sync, inside each agent | Agent answer faithfulness vs its own retrieved data — primary hallucination defence |
| 3 | **Output Guardrail** | Rule-based | Async, post-stream | PII in final response, compliance keywords, security |
| 4 | **Final NLI** | Haiku 4.5 | Async, post-stream | Synthesized answer vs aggregated sub-answers — catches hallucinations added during Sonnet synthesis step |

**Why Final NLI after streaming:** Sonnet synthesis can introduce plausible-but-wrong claims when stitching multiple sub-answers together. Final NLI catches this failure mode. It runs async so it does not block the token stream — the rep sees the answer immediately, then receives a `{type: "verified" | "warning"}` SSE event as a verdict indicator.

**Streaming strategy (Option C):** Stream tokens to client immediately → Output Guardrail and Final NLI run in parallel on the buffered complete response → send verdict event.

---

### 7. Data Layer

#### PostgreSQL — Customer 360

Structured customer data: demographics, KYC, credit score, segment, product portfolio (CASA accounts, loans, credit cards, term deposits, bancassurance), transaction history, open support cases, long-term memory records (behavior profile, product offer history, life event timeline).

Accessed via Hasura GraphQL by: QueryDispatcher, session context loader (Orchestrator node ①), customer 360 right panel.

#### OpenSearch — Product & Contract Documents

Unstructured and semi-structured content indexed for hybrid retrieval:
- Product descriptions, T&Cs, pricing policies, promotion campaigns
- Contract clause text (linked to Neo4j nodes by `contract_id`)
- Conversation summaries (long-term memory vector store)
- Customer behavior profiles (semantic retrieval)

#### Neo4j — Contract Graph

Customer contract entity relationships:
```
Customer -[HAS]-> Contract -[IS_TYPE]-> BancaInsurance
Contract -[HAS_CLAUSE]-> Clause
Contract -[LINKED_TO]-> Product
```

Stores: contract metadata, status, parties, clause references. Full clause text lives in OpenSearch.

#### Redis — Cache

Four namespaces. Agents never call Redis directly — all cache reads/writes go through the Orchestrator node or dedicated cache layer.

| Namespace | Key Pattern | TTL | Invalidation |
|---|---|---|---|
| Session context | `session:{rep_id}:{customer_id}:{date}` | 4h | Session end |
| Query results | `query:{customer_id}:{query_type}:{params_hash}` | 30min–24h (tiered) | Write-through + TTL |
| Contract data | `contract:{customer_id}` | 12h | `CONTRACT_UPDATED` event from Data Lake |
| RAG results | `rag:{query_hash}` | 6h | Document ingestion event |

**Tiered TTL by data change frequency:**

| Data Type | TTL |
|---|---|
| Customer demographics | 24h |
| Product portfolio | 6h |
| Loan / term deposit balance | 6h |
| Transaction aggregations | 30min |
| Contracts | 12h + event-triggered |
| RAG / product documents | 6h + ingestion event |
| Session context | Session duration (max 4h) |

---

### 8. RAG Pipeline

#### Ingestion (Offline)
```
Markdown / PDF documents
  → Chunking: 512 tokens, 10% overlap (51 tokens)
  → Cohere embed-multilingual-v3 (batch embedding)
  → OpenSearch index with metadata:
      { doc_type, product_name, language, effective_date, contract_id }
```

#### Retrieval (Online, per agent query)
```
Step 1 — Hybrid Search (parallel):
  BM25 keyword search    → top-10 chunks  (weight 0.3 in RRF)
  Semantic vector search → top-10 chunks  (weight 0.7 in RRF)
  RRF merge: score = 0.3 × 1/(rank_bm25 + 60) + 0.7 × 1/(rank_sem + 60)
  → ~12–15 unique chunks after deduplication

Step 2 — Re-ranking:
  Cross-encoder re-scores ~12–15 chunks against the original query
  Returns top-5 most relevant chunks
  (10+10 → ~15 unique is ~40% less cross-encoder compute vs 20+20 → 20)

Step 3 — Context assembly:
  Top-5 chunks + source citations → LLM prompt
```

**Why top-10 per modality (not 20):** BM25 and semantic search have significant result overlap — fetching 10 each yields ~12–15 unique chunks after RRF, sufficient for re-ranking to top-5. Fetching 20 each gives ~20 unique but doubles cross-encoder compute and token cost with negligible recall improvement.

---

### 9. Evaluation Dataset

RAGAS evaluation requires a **golden dataset** — without it, evaluation scores are meaningless. This must be built before any offline evaluation run.

#### Dataset Composition (~300–400 examples total)

| Type | Volume | Source |
|---|---|---|
| Product knowledge Q&A | ~200 examples (10–15 per product × 15 products) | LLM-draft from product documents → human review |
| Contract clause reasoning | ~50 examples | Hand-crafted from known clause scenarios (e.g., Clause 7.3 VIP medical: continuous ≥12mo + Gold/Platinum/Elite → 25M VND) |
| Structured query (QueryDispatcher) | ~50 examples | Sampled from seed data; query + expected SQL + expected result |
| Adversarial / edge cases | ~30 examples | Cross-product confusion; ambiguous pronouns; out-of-scope questions |

**Format (JSONL):**
```json
{
  "question": "Khách hàng này có đủ điều kiện hưởng quyền lợi y tế khẩn cấp khi đi nước ngoài không?",
  "ground_truth": "Có, vì hợp đồng đã duy trì liên tục 14 tháng và khách hàng đang ở phân khúc Platinum.",
  "relevant_chunks": ["clause_7_3_vip_medical", "contract_status_active"],
  "metadata": { "type": "contract_reasoning", "product": "banca_life_protection_plus" }
}
```

**Generation workflow:**
1. Use Claude to draft Q/A pairs from each product document (prompt: "generate 15 diverse questions...")
2. Human review: fix wrong answers, add tricky edge cases, verify clause references
3. Store in `data/evaluation/golden_dataset.jsonl`
4. Gate every architecture change (chunking, retrieval config, model swap) on this dataset

#### Evaluation Cadence

- **Online (20% sampling):** Every 5th production query → log question + retrieved chunks + answer → async RAGAS job hourly → push scores to LangSmith → alert if Faithfulness < 0.8
- **Offline (gated):** Full golden dataset run before any change to chunking strategy, retrieval config, re-ranker, or LLM model — gate on Faithfulness ≥ 0.85, Context Recall ≥ 0.80

**RAGAS metrics tracked:** Faithfulness, Answer Relevancy, Context Precision, Context Recall

---

### 10. Memory Model

#### Short-term Memory (In-session, ephemeral)
Managed by LangGraph `messages` state. Holds the running conversation, tool call results, and intermediate reasoning for the current session. Discarded when the session ends — never persisted.

#### Long-term Memory (Persistent, cross-session)

Owned and loaded by the **Orchestrator (LangGraph node ①)**, not by FastAPI. Loaded on first message in a session, injected into the LangGraph state as the system prompt, cached in Redis for the session duration.

| Content | Store | Notes |
|---|---|---|
| Conversation summaries | OpenSearch (vector) | Last 3–5 daily summaries loaded at session start |
| Customer behavior profile | PostgreSQL | Call preferences, communication style, objections |
| Product offer history | PostgreSQL | Products offered, dates, outcomes (accepted/rejected) |
| Life event timeline | PostgreSQL | Loan maturities, insurance renewals, milestones |
| Segment gap history | PostgreSQL | Distance to VIP threshold over time |

**Scoping:** Long-term memory is scoped to the **customer** — any rep who manages that customer sees the same memory.

**Session lifecycle (Orchestrator owns this, not FastAPI):**
```
Session START (first /chat/stream call for a session_id):
  Orchestrator node ① checks Redis for session:{rep}:{cust}
  On miss:
    Load customer 360 from PostgreSQL via Hasura
    Load last 3–5 conversation summaries from OpenSearch
    Load behavior profile + offer history from PostgreSQL
    Assemble system prompt
    Cache assembled context in Redis (TTL: 4h)
  On hit:
    Use cached context directly

Session END (/api/sessions/end):
  Haiku summarizes full conversation
  Write summary to OpenSearch (vector store)
  Update behavior profile in PostgreSQL (new observations)
  Clear session cache from Redis
```

---

### 11. Observability — LangSmith

- Every LangGraph node execution traced (inputs, outputs, latency, token usage, model)
- Tool calls (Hasura GraphQL, Neo4j, OpenSearch, Redis) logged per execution
- NLI check results (pass/fail + score) logged per agent
- Prompt versions tracked and pinned per environment (dev / staging / prod)
- RAGAS online evaluation scores surfaced in LangSmith dashboard
- Alerts: Faithfulness < 0.8, p95 latency > 20s

---

## Non-Functional Requirements

### Latency Targets

| Scenario | First Token | Full Response |
|---|---|---|
| Structured query — cache hit | ~2s | ~4s |
| Structured query — cache miss (GraphQL) | ~3s | ~5s |
| Single RAG (product or contract) | ~4s | ~8s |
| Multi-agent: 2 parallel branches | ~5s | ~12s |
| Multi-agent: 3+ branches (full fan-out) | ~7s | ~18–20s |

### Latency Breakdown (multi-agent worst case)

| Step | Duration |
|---|---|
| Input Guardrail | 200ms |
| IntentRewriteNode (Haiku) | 800ms |
| Parallel agents (bottleneck: ContractKnowledgeAgent) | ~4,000ms |
| — Neo4j traversal | 500ms |
| — OpenSearch hybrid search | 400ms |
| — Cross-encoder re-rank (15 chunks) | 400ms |
| — Sonnet reasoning | 2,000ms |
| — Per-answer NLI (Haiku) | 700ms |
| AggregatorNode | 100ms |
| Sonnet synthesis — first token | 500ms |
| **First token to rep** | **~5.6s** |
| Sonnet synthesis — full stream | 3–8s streaming |
| **Full response** | **~15–20s** |

### Other Requirements

| Requirement | Target |
|---|---|
| Customer 360 panel load time | < 2s |
| Structured query — cache hit | < 100ms |
| Input guardrail check | < 200ms |
| Per-answer NLI check (Haiku) | < 700ms |
| RAG Faithfulness score | ≥ 0.85 |
| Context Recall score | ≥ 0.80 |
| Cache hit rate — QueryDispatcher | > 70% |
| Data visibility | Rep sees only their assigned customers |
| Monetary display | VND, readable format (e.g., 1.2B VND) |
| Language | Vietnamese primary; English product terms preserved |
