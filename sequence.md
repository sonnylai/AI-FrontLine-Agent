# AI FrontLine Agent — Sequence Diagrams

---

## Diagram 1: Session Start

When a sales rep opens the chat for a specific customer. Loads long-term memory and customer 360 data, assembles the system prompt, caches it for the session.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend (HTML)
    participant API as FastAPI
    participant Auth as Auth Middleware
    participant Redis
    participant PG as PostgreSQL
    participant OS as OpenSearch

    Rep->>FE: Opens customer chat (customer_id)
    FE->>API: POST /api/sessions/start {rep_id, customer_id}

    API->>Auth: Validate JWT token
    Auth-->>API: PASS — rep is authorized for this customer

    API->>Redis: GET session:{rep_id}:{customer_id}:{date}
    Redis-->>API: MISS

    par Load customer profile
        API->>PG: Fetch customer 360 (profile, products, transactions summary)
        PG-->>API: Customer data
    and Load long-term memory
        API->>PG: Fetch behavior profile + product offer history
        PG-->>API: Behavior profile, offer history
        API->>OS: Vector search — last 3 conversation summaries for this customer
        OS-->>API: Conversation summaries
    end

    API->>API: Assemble system prompt (profile + summaries + behavior)
    API->>Redis: SET session:{rep_id}:{customer_id}:{date} TTL 4h

    API-->>FE: {session_id, customer_360_data}
    FE->>FE: Render right panel (Customer 360)
    FE-->>Rep: UI ready — right panel populated
```

---

## Diagram 2: Session End

When the rep closes the chat or ends the session. Summarizes the conversation and writes back to long-term memory.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend (HTML)
    participant API as FastAPI
    participant CS as Claude Sonnet
    participant PG as PostgreSQL
    participant OS as OpenSearch
    participant Redis

    Rep->>FE: Closes chat / ends session
    FE->>API: POST /api/sessions/end {session_id, customer_id}

    API->>CS: Summarize full conversation (short-term messages state)
    Note over CS: Extracts: topics discussed, products offered,<br/>objections raised, follow-up items, behavior observations
    CS-->>API: Conversation summary + behavior observations

    par Write to long-term memory
        API->>OS: Store conversation summary (vector embed + index)
        OS-->>API: Stored
    and Update behavior profile
        API->>PG: Update behavior profile (new observations)
        PG-->>API: Updated
    and Log offer outcomes
        API->>PG: Record products pitched this session + outcomes
        PG-->>API: Recorded
    end

    API->>Redis: DELETE session:{rep_id}:{customer_id}:{date}
    Redis-->>API: Cleared

    API-->>FE: Session ended
    FE-->>Rep: Chat cleared
```

---

## Diagram 3: Multi-Agent Chat Query (Fan-out / Fan-in)

Main flow for a complex query requiring two agents in parallel. Example query from sales rep:
> *"How much has this customer spent on Grab in the last 90 days, and does his Banca contract qualify for the premium travel insurance discount?"*

This triggers `TRANSACTION_QUERY` (→ QueryDispatcher) and `CONTRACT_QUERY` (→ ContractKnowledgeAgent) in parallel.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend (HTML)
    participant API as FastAPI
    participant IG as Input Guardrail
    participant Orch as Orchestrator
    participant IR as IntentRewrite Node (Haiku)
    participant QD as Query Dispatcher
    participant CKA as Contract Knowledge Agent
    participant NLI as NLI Checker
    participant AGG as Aggregator Node
    participant CS as Claude Sonnet
    participant OG as Output Guardrail
    participant Redis
    participant PG as PostgreSQL
    participant GDB as Graph DB
    participant OS as OpenSearch

    Rep->>FE: Types query message
    FE->>API: POST /api/chat/stream {session_id, customer_id, message}

    API->>IG: Validate input
    Note over IG: Check: prompt injection, PII in prompt,<br/>topic relevance, security threats
    IG-->>API: PASS

    API->>Orch: Route to agent pipeline
    Orch->>Redis: GET session:{rep_id}:{customer_id}:{date}
    Redis-->>Orch: HIT — system prompt context loaded

    Orch->>IR: message + session context
    Note over IR: Single Haiku call:<br/>1. Classify intents<br/>2. Rewrite sub-questions with structured params
    IR-->>Orch: sq1 (TRANSACTION_QUERY → QueryDispatcher)<br/>sq2 (CONTRACT_QUERY → ContractKnowledgeAgent)

    par Fan-out: sq1 → QueryDispatcher (No LLM)
        Orch->>QD: sq1 {query_type: aggregate_by_merchant, customer_id, merchant: GRAB, date_from, date_to}
        QD->>Redis: GET query:CUST_001:aggregate_by_merchant:{hash}
        Redis-->>QD: MISS
        QD->>PG: GraphQL — aggregate Grab transactions for CUST_001
        PG-->>QD: {total_amount: 1240000, count: 18, currency: VND}
        QD->>Redis: SET query:CUST_001:aggregate_by_merchant:{hash} TTL 30min
        QD->>NLI: Validate answer vs raw query result
        NLI-->>QD: PASS
        QD-->>AGG: sq1 answer validated ✓

    and Fan-out: sq2 → ContractKnowledgeAgent (Sonnet)
        Orch->>CKA: sq2 {customer_id, question: "Banca contract qualify for travel insurance discount?"}

        CKA->>Redis: GET contract:CUST_001
        Redis-->>CKA: MISS
        CKA->>GDB: Traverse Customer → Contract → Policy → Clause
        GDB-->>CKA: Contract BC-2024-441, type: BancaLifeInsurance, status: active
        CKA->>Redis: SET contract:CUST_001 TTL 12h

        CKA->>Redis: GET rag:{query_hash} (semantic cache check)
        Redis-->>CKA: MISS
        CKA->>OS: Hybrid search — BM25 + Cohere semantic (top 20 each)
        OS-->>CKA: Top 20 merged chunks (via RRF)
        CKA->>OS: Re-rank with cross-encoder
        OS-->>CKA: Top 5 chunks
        CKA->>Redis: SET rag:{query_hash} TTL 6h

        CKA->>CS: Contract graph + top 5 chunks → reason about eligibility
        CS-->>CKA: "Clause 7.3 grants 10% discount on premium renewal for active Banca holders with continuous coverage > 1 year"
        CKA->>NLI: Validate answer vs retrieved clause text
        NLI-->>CKA: PASS
        CKA-->>AGG: sq2 answer validated ✓
    end

    AGG->>AGG: Merge sq1 + sq2 validated answers into context block
    AGG->>CS: Synthesize final response from merged context
    Note over CS: Streams tokens as generated

    loop Token streaming
        CS-->>OG: Token chunk
        OG->>OG: PII masking check on chunk
        OG-->>FE: SSE event {type: "token", content: "..."}
        FE-->>Rep: Text appears progressively
    end

    CS-->>OG: Stream complete

    Note over OG,NLI: Async — runs in parallel after stream ends
    OG->>NLI: Final NLI check on complete buffered response
    NLI-->>OG: PASS — no hallucination added during synthesis
    OG-->>FE: SSE event {type: "verified"}
    FE-->>Rep: ✓ Verified indicator shown

```

---

## Diagram 4: NLI Failure — Partial Answer Handling

What happens when one sub-agent fails the NLI check. The system delivers a partial answer rather than failing the whole request.

```mermaid
sequenceDiagram
    participant Orch as Orchestrator
    participant QD as Query Dispatcher
    participant CKA as Contract Knowledge Agent
    participant NLI as NLI Checker
    participant AGG as Aggregator Node
    participant CS as Claude Sonnet
    participant OG as Output Guardrail
    participant FE as Frontend

    par Fan-out
        QD-->>NLI: Validate sq1 answer
        NLI-->>QD: PASS ✓
        QD-->>AGG: sq1 answer — verified

    and Fan-out
        CKA-->>NLI: Validate sq2 answer
        Note over NLI: Answer references a clause<br/>not present in retrieved chunks
        NLI-->>CKA: FAIL ✗
        CKA->>CKA: Retry with broader retrieval (top 10 chunks)
        CKA-->>NLI: Validate retry answer
        NLI-->>CKA: FAIL ✗ (second attempt)
        CKA-->>AGG: sq2 answer — flagged as UNCERTAIN
    end

    AGG->>CS: Merge context — mark sq2 as uncertain
    Note over CS: Instructed to acknowledge uncertainty<br/>for sq2 in its response

    CS-->>OG: Stream response
    Note over CS: "Grab spend: 1.24M VND (18 transactions). ⚠ I could not fully verify<br/>the Banca contract eligibility — please review the policy document directly."

    OG-->>FE: Stream tokens + SSE event {type: "warning"}
    FE-->>FE: Show ⚠ warning banner alongside response
```

---

## Diagram 5: Simple Query — QueryDispatcher Cache Hit

Fast path for a common structured query. No LLM involved, served from cache in milliseconds.

```mermaid
sequenceDiagram
    participant Rep as Sales Rep
    participant FE as Frontend
    participant API as FastAPI
    participant IG as Input Guardrail
    participant IR as IntentRewrite Node (Haiku)
    participant QD as Query Dispatcher
    participant NLI as NLI Checker
    participant CS as Claude Sonnet
    participant OG as Output Guardrail
    participant Redis

    Rep->>FE: "What products does this customer currently have?"
    FE->>API: POST /api/chat/stream

    API->>IG: Validate input — PASS
    API->>IR: message + session context
    IR-->>API: sq1 {query_type: product_portfolio_summary, customer_id: CUST_001}

    API->>QD: sq1 params
    QD->>Redis: GET query:CUST_001:product_portfolio_summary
    Redis-->>QD: HIT — {accounts: 2, loans: 1, banca: 1, term_deposits: 0, credit_cards: 1}

    QD->>NLI: Validate cached result
    NLI-->>QD: PASS (deterministic data, no LLM involved)

    QD-->>CS: Cached result → format as natural language response
    CS-->>OG: Stream tokens
    OG-->>FE: SSE stream
    FE-->>Rep: "Mr A currently holds: 2 CASA accounts, 1 home loan (450M VND remaining),<br/>1 active Banca Life Insurance contract, and 1 Gold Credit Card."
    OG-->>FE: SSE event {type: "verified"}
```
