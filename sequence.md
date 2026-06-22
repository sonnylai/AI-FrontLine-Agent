# AI FrontLine Agent — Sequence Diagrams

---

## Diagram 1: Session Start

When a sales rep opens the chat for a specific customer. Pre-warms Redis with customer 360 data and conversation summaries so the first chat message doesn't pay the load cost.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend (HTML)
    participant API as FastAPI
    participant Redis
    participant Hasura
    participant PG as PostgreSQL
    participant OS as OpenSearch

    Rep->>FE: Opens customer chat (customer_id)
    FE->>API: POST /api/sessions/start {customer_id}

    Note over API: JWT validated via Depends(get_current_rep)

    API->>Redis: GET session:{session_id}
    Redis-->>API: MISS

    par Load customer 360
        API->>Hasura: GraphQL LoadSession — 8 fields + products_held
        Hasura->>PG: SQL SELECT
        PG-->>Hasura: Customer row
        Hasura-->>API: customer_360 (8 minimal fields)
    and Load long-term memory
        API->>OS: Search conversation-summaries — last 5 for customer_id
        OS-->>API: Conversation summaries (sorted by date desc)
    end

    API->>Redis: SET session:{session_id} TTL 4h
    API-->>FE: {session_id, customer_id}
    FE-->>Rep: UI ready — session open
```

---

## Diagram 2: Session End

When the rep closes the chat. Haiku summarizes the conversation and writes to long-term memory, then clears Redis.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend (HTML)
    participant API as FastAPI
    participant Haiku as Claude Haiku 4.5
    participant OS as OpenSearch
    participant Redis

    Rep->>FE: Closes chat / ends session
    FE->>API: POST /api/sessions/end {session_id, customer_id, messages: [...]}

    Note over API: JWT validated via Depends(get_current_rep)

    API->>Haiku: Summarize conversation (full message list)
    Note over Haiku: Extracts: summary, key_concerns,<br/>products_discussed, sentiment
    Haiku-->>API: JSON summary

    API->>OS: Index summary to conversation-summaries
    OS-->>API: Stored

    API->>Redis: DELETE session:{session_id}
    Redis-->>API: Cleared

    API-->>FE: 204 No Content
    FE-->>Rep: Chat cleared
```

---

## Diagram 3: Multi-Agent Chat Query (Fan-out / Fan-in)

Main flow for a complex query requiring two agents in parallel. Example:
> *"How much has this customer spent on Grab in the last 90 days, and does his Banca contract qualify for the premium travel insurance discount?"*

This triggers `TRANSACTION_QUERY` (→ QueryDispatcher) and `CONTRACT_QUERY` (→ ContractKnowledgeAgent) in parallel.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend (HTML)
    participant API as FastAPI
    participant Orch as Orchestrator (LangGraph)
    participant IR as IntentRewrite Node (Haiku)
    participant QD as QueryDispatcher
    participant CKA as ContractKnowledgeAgent
    participant CS as Claude Sonnet 4.6
    participant Cohere as Cohere API
    participant AGG as Aggregator Node
    participant OG as Output Guardrail
    participant FN as Final NLI (Haiku)
    participant Redis
    participant Hasura
    participant PG as PostgreSQL
    participant Neo4j
    participant OS as OpenSearch

    Rep->>FE: Types query message
    FE->>API: POST /api/chat/stream {session_id, customer_id, message}
    Note over API: JWT validated via Depends(get_current_rep)

    API->>Orch: orchestrator.run(...) — LangGraph ainvoke

    Note over Orch: Node ① — load_session_context
    Orch->>Redis: GET session:{session_id}
    Redis-->>Orch: HIT — customer_360 + summaries injected into state

    Note over Orch: Node ② — input_guard (rule-based regex, ~1ms)
    Orch->>Orch: input_guardrail.check(message) — PASS

    Note over Orch: Node ③ — intent_rewrite
    Orch->>IR: message + customer context
    Note over IR: Single Haiku call: classify intents,<br/>rewrite sub-questions, resolve relative dates
    IR-->>Orch: sub_questions [sq1: TRANSACTION_QUERY→QD, sq2: CONTRACT_QUERY→CKA]

    Note over Orch: _fan_out edge — LangGraph Send() API dispatches parallel branches

    par Fan-out: sq1 → QueryDispatcher (No LLM)
        Orch->>QD: branch_state {query_type: aggregate_by_merchant, params: {merchant_name: "grab", date_from, date_to}}
        QD->>Redis: GET query:CUST-001:aggregate_by_merchant:{hash}
        Redis-->>QD: MISS
        QD->>Hasura: GraphQL AggMerchantByName {cid, from: timestamptz, to: timestamptz, name: "%grab%"}
        Hasura->>PG: SQL SELECT
        PG-->>Hasura: transaction rows
        Hasura-->>QD: {transactions: [...]}
        QD->>Redis: SET query:...:aggregate_by_merchant:{hash} TTL 30min
        QD-->>AGG: {agent: "query_dispatcher", answer: "...", verified: true}

    and Fan-out: sq2 → ContractKnowledgeAgent
        Orch->>CKA: branch_state {rewritten_query: "Banca contract qualify for travel insurance discount?"}

        CKA->>Redis: GET contract:CUST-001
        Redis-->>CKA: MISS
        CKA->>Neo4j: Traverse Customer→Contract→Policy→Clause
        Neo4j-->>CKA: contract metadata + clause references
        CKA->>Redis: SET contract:CUST-001 TTL 6h

        CKA->>Redis: GET rag:{query_hash}
        Redis-->>CKA: MISS

        par Hybrid RAG search (top-10 each)
            CKA->>OS: BM25 keyword search → top-10 chunks
            OS-->>CKA: top-10 BM25 hits
        and
            CKA->>Cohere: embed query (embed-multilingual-v3.0)
            Cohere-->>CKA: query vector
            CKA->>OS: KNN vector search → top-10 chunks
            OS-->>CKA: top-10 KNN hits
        end

        CKA->>CKA: RRF merge (BM25 weight 0.3, KNN weight 0.7) → ~12-18 candidates
        CKA->>Cohere: rerank-multilingual-v3.0 top-5
        Cohere-->>CKA: top-5 reranked chunks
        CKA->>OS: Sibling expansion — fetch chunk_index+1 for same h3_section
        OS-->>CKA: sibling chunks (if any)
        CKA->>Redis: SET rag:{query_hash} TTL 6h

        CKA->>CS: contract graph context + RAG chunks → reason about eligibility
        CS-->>CKA: answer text
        CKA->>CKA: NLI heuristic check — term overlap + number grounding (~1ms, no LLM)
        CKA-->>AGG: {agent: "contract", answer: "...", verified: true/false, warning: ...}
    end

    Note over AGG: Node ⑤ — Aggregator
    AGG->>AGG: Merge all agent results into synthesis prompt
    AGG->>CS: Synthesize final response (streaming)

    loop Token streaming — Sonnet writes to async queue
        CS-->>AGG: token chunk
        AGG-->>API: SSE {type: "token", content: "..."}
        API-->>FE: SSE event
        FE-->>Rep: Text appears progressively
    end

    Note over AGG,FN: Stream complete — post-stream checks run in parallel (asyncio.gather)
    par Post-stream safety (parallel)
        AGG->>OG: output_guardrail.check(full_answer)
        Note over OG: Regex: PII patterns + compliance phrases
        OG-->>AGG: (passed: bool, warning: str|None)
    and
        AGG->>FN: final_nli.check(full_answer, agent_results)
        Note over FN: Haiku: is synthesis consistent<br/>with all agent answers?
        FN-->>AGG: (consistent: bool, issues: str|None)
    end

    AGG-->>API: SSE {type: "done", verified: bool, warning: str|null}
    API-->>FE: SSE event
    FE-->>Rep: ✓ verified or ⚠ warning indicator shown
```

---

## Diagram 4: NLI Failure — Partial Answer Handling

What happens when the ContractKnowledgeAgent fails the per-agent NLI check. No retry — the flagged answer passes through to the Aggregator with `verified=False` so Sonnet can acknowledge uncertainty.

```mermaid
sequenceDiagram
    participant Orch as Orchestrator (LangGraph)
    participant QD as QueryDispatcher
    participant CKA as ContractKnowledgeAgent
    participant CS as Claude Sonnet 4.6
    participant AGG as Aggregator Node
    participant OG as Output Guardrail
    participant FN as Final NLI (Haiku)
    participant API as FastAPI
    participant FE as Frontend

    Note over Orch: _fan_out dispatches both branches in parallel

    par Fan-out
        Orch->>QD: sq1 — aggregate_by_merchant
        Note over QD: No NLI — verified=True always (deterministic Postgres data)
        QD-->>AGG: {verified: true, answer: "Grab spend: 1.24M VND (18 transactions)"}

    and Fan-out
        Orch->>CKA: sq2 — contract clause eligibility
        CKA->>CKA: Retrieve context, call Sonnet, run heuristic NLI check
        Note over CKA: NLI FAIL — answer references a clause<br/>not found in retrieved chunks (overlap < 20%)
        Note over CKA: No retry — flagged answer passed through
        CKA-->>AGG: {verified: false, warning: "Câu trả lời chứa thông tin không có trong nguồn dữ liệu"}
    end

    AGG->>CS: Merge context — sq2 marked ⚠ UNCERTAIN
    Note over CS: System prompt instructs Sonnet to<br/>acknowledge uncertainty for unverified answers

    CS-->>AGG: "Grab spend: 1.24M VND (18 transactions). ⚠ Không thể xác minh đầy đủ điều khoản hợp đồng Banca — vui lòng kiểm tra trực tiếp tài liệu hợp đồng."

    loop Token streaming
        AGG-->>API: SSE {type: "token", content: "..."}
        API-->>FE: SSE event
    end

    par Post-stream checks (parallel)
        AGG->>OG: output_guardrail.check(full_answer) — PASS
        AGG->>FN: final_nli.check(full_answer, agent_results)
        Note over FN: Haiku detects sq2 was uncertain —<br/>synthesis correctly reflected that
        FN-->>AGG: {consistent: true}
    end

    AGG-->>API: SSE {type: "done", verified: false, warning: "..."}
    API-->>FE: SSE event
    FE-->>FE: Show ⚠ warning indicator alongside response
    FE-->>FE: Rep sees partial answer with uncertainty notice
```

---

## Diagram 5: Simple Query — QueryDispatcher Cache Hit

Fast path for a common structured query. No LLM in QueryDispatcher — pure Python formatting. Aggregator still calls Sonnet for final synthesis.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend
    participant API as FastAPI
    participant Orch as Orchestrator (LangGraph)
    participant IR as IntentRewrite Node (Haiku)
    participant QD as QueryDispatcher
    participant AGG as Aggregator Node
    participant CS as Claude Sonnet 4.6
    participant OG as Output Guardrail
    participant FN as Final NLI (Haiku)
    participant Redis

    Rep->>FE: "What products does this customer currently have?"
    FE->>API: POST /api/chat/stream
    Note over API: JWT validated via Depends(get_current_rep)

    API->>Orch: orchestrator.run(...)

    Note over Orch: Node ① — session context already in Redis (HIT)
    Note over Orch: Node ② — input_guard PASS
    Note over Orch: Node ③ — intent_rewrite

    Orch->>IR: message + context
    IR-->>Orch: sub_questions [{query_type: product_portfolio_summary, customer_id: CUST-001}]

    Note over Orch: _fan_out → single branch to QueryDispatcher

    Orch->>QD: branch_state {query_type: product_portfolio_summary}
    QD->>Redis: GET query:CUST-001:product_portfolio_summary:{hash}
    Redis-->>QD: HIT — cached result

    Note over QD: Pure Python _fmt_portfolio() formats result<br/>No NLI — verified=True always (deterministic data)
    QD-->>AGG: {agent: "query_dispatcher", answer: "Danh mục: CASA x2, Home Loan, Banca, Gold Card", verified: true}

    Note over AGG: Node ⑤ — Aggregator calls Sonnet for final synthesis
    AGG->>CS: Synthesize response from QueryDispatcher result
    CS-->>AGG: token stream

    loop Token streaming
        AGG-->>API: SSE {type: "token", content: "..."}
        API-->>FE: SSE event
        FE-->>Rep: Text appears progressively
    end

    par Post-stream checks (parallel)
        AGG->>OG: output_guardrail.check(full_answer) — PASS
        AGG->>FN: final_nli.check(full_answer, agent_results) — PASS
    end

    AGG-->>API: SSE {type: "done", verified: true}
    API-->>FE: SSE event
    FE-->>Rep: ✓ Verified indicator shown
```

---

## Key Design Decisions

| Concern | Mechanism |
|---|---|
| Auth | JWT validated per-request via `Depends(get_current_rep)`; Hasura claims embedded for row-level security |
| Session context | Pre-warmed at `/sessions/start`; Redis cache (4h TTL) — avoids re-fetching Hasura + OpenSearch on every message |
| Query cache | Per-query Redis keys with tiered TTL (30min transactions, 6h contracts/deposits, 24h demographics) |
| Structured data | GraphQL via Hasura → Postgres — no LLM, `verified=True` always, pure Python formatting |
| RAG data | OpenSearch BM25 + KNN (top-10 each) → RRF → Cohere rerank → top-5 + sibling expansion |
| Intent routing | Haiku LLM → fan-out to 1–N agents in parallel via LangGraph `Send()` |
| Synthesis | Sonnet streams tokens to async queue → FastAPI yields SSE — no buffering delay |
| Safety | 4 layers: input regex (node ②, sync) → per-agent NLI heuristic (sync, ~1ms) → output regex + final NLI Haiku (both post-stream, parallel) |
| Observability | LangSmith `@traceable` spans: RAG·BM25/KNN/RRF/Rerank/Sibling, QueryDispatcher·Hasura, NLI·PerAgent/OutputGuardrail/Final |
