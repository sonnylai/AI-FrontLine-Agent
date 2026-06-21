# Request Flow — AI FrontLine Agent V2

## Step-by-Step Explanation

### Step 1 — Client sends POST /chat
The browser/frontend sends `POST /chat` with a JSON body (`ChatRequest`) and a Bearer JWT in the `Authorization` header.

**Classes involved:**
- `ChatRequest` ([src/models/chat.py](src/models/chat.py)) — Pydantic model: `customer_id`, `message`, `session_id`, `conversation_history`

---

### Step 2 — JWT Authentication (Middleware)
FastAPI's dependency injection runs `get_current_rep()` before the route handler.

**Classes / functions:**
- `HTTPBearer` (FastAPI) — extracts token from header
- `get_current_rep()` ([src/middleware/jwt_auth.py](src/middleware/jwt_auth.py)) — FastAPI `Security` dependency
- `decode_token()` ([src/middleware/jwt_auth.py](src/middleware/jwt_auth.py)) — decodes & validates JWT using `jose.jwt`
- Returns a `dict` with `sub` (rep_id), `name`, Hasura claims

If invalid → HTTP 401 immediately, pipeline never starts.

---

### Step 3 — Chat Router opens SSE stream
The validated request hits the route handler. A `StreamingResponse` (Server-Sent Events) is returned immediately so the client starts receiving streamed tokens.

**Classes / functions:**
- `chat()` ([src/api/chat.py:57](src/api/chat.py)) — `@router.post("")` handler
- `stream_pipeline()` ([src/api/chat.py:20](src/api/chat.py)) — creates an `asyncio.Queue` shared between the pipeline and the SSE writer
- `StreamingResponse` (FastAPI/Starlette) — wraps the async generator
- `sse()` ([src/api/chat.py:12](src/api/chat.py)) — formats each event as `data: {...}\n\n`

Event types streamed: `thinking` · `agent_result` · `token` · `done` · `error`

---

### Step 4 — Orchestrator builds initial state and starts LangGraph
`orchestrator.run()` constructs the full `AgentState` and calls `_graph.ainvoke()`.

**Classes / functions:**
- `orchestrator.run()` ([src/agents/orchestrator.py:156](src/agents/orchestrator.py))
- `AgentState` ([src/agents/state.py](src/agents/state.py)) — `TypedDict` holding all pipeline state
- `StateGraph` (LangGraph) — compiled at module load as `_graph`
- `RunnableConfig` — carries `stream_queue` in `configurable`, LangSmith callbacks

---

### Node ① — load_session_context
**Route:** `START → load_session_context`

Loads customer context. Redis is checked first; on a miss it fetches from Hasura + OpenSearch and caches the result.

**Classes / functions:**
- `_load_session_context()` ([src/agents/orchestrator.py:25](src/agents/orchestrator.py))
- `session_store.load()` ([src/cache/session_store.py:108](src/cache/session_store.py))
- `redis_client.get/set()` ([src/cache/redis_client.py](src/cache/redis_client.py)) — key `session:{session_id}`, TTL=4h
- `hasura_client.query(_CUSTOMER_QUERY)` ([src/db/hasura_client.py:30](src/db/hasura_client.py)) — GraphQL over HTTP to Hasura → PostgreSQL
- `_load_summaries()` ([src/cache/session_store.py:56](src/cache/session_store.py)) — OpenSearch `conversation-summaries` index
- Populates `AgentState.customer_360` (8 fields) and `AgentState.long_term_summaries`

---

### Node ② — input_guard
**Route:** `load_session_context → input_guard`

Sync, zero-latency regex-based safety check. No LLM involved.

**Classes / functions:**
- `_input_guard()` ([src/agents/orchestrator.py:40](src/agents/orchestrator.py))
- `input_guardrail.check()` ([src/safety/input_guardrail.py:26](src/safety/input_guardrail.py)) — checks PII patterns, SQL injection, prompt injection, off-topic keywords

**Routing after:**
- `blocked=True` → `_block_and_done()` → emits `error` + `done` SSE → `END`
- `blocked=False` → `intent_rewrite`

---

### Node ③ — intent_rewrite (Haiku LLM)
**Route:** `input_guard → intent_rewrite`

Single Haiku call that classifies the message into one or more `sub_questions`, each targeting a specific agent. Also resolves pronouns and time expressions (e.g. "3 tháng qua" → concrete dates).

**Classes / functions:**
- `_intent_rewrite()` → `intent_rewrite.run()` ([src/agents/nodes/intent_rewrite.py:103](src/agents/nodes/intent_rewrite.py))
- `anthropic.AsyncAnthropic.messages.create()` — model: `claude-haiku-4-5`
- Returns `sub_questions[]`, `active_agents[]`, `rewritten_query`

Each `sub_question` entry specifies: `agent`, `intent`, `query_type`, `params`, `rewritten_query`

---

### Node ④ — Fan-out (parallel agent dispatch)
**Route:** `intent_rewrite → [parallel Send() calls]`

`_fan_out()` converts each `sub_question` into a LangGraph `Send()` which dispatches the corresponding agent node in parallel.

**Classes / functions:**
- `_fan_out()` ([src/agents/orchestrator.py:91](src/agents/orchestrator.py)) — returns `list[Send]`
- `Send` (LangGraph) — dispatches named node with a copy of state

#### Path A — query_dispatcher (structured data from Postgres)
Triggered when intent = `TRANSACTION_QUERY`. No LLM. Pure GraphQL template execution.

- `query_dispatcher.run()` ([src/agents/query_dispatcher.py:309](src/agents/query_dispatcher.py))
- Redis check: key `query:{customer_id}:{query_type}:{params_hash}` (tiered TTL: 30m–24h)
- On miss: `hasura_client.query(template, vars)` → GraphQL → Postgres
- Templates: `_Q_PROFILE`, `_Q_PORTFOLIO`, `_Q_AGG_CATEGORY`, `_Q_CASA`, `_Q_LOAN`, etc.
- `@traceable` LangSmith span via `_log_hasura()` ([src/agents/query_dispatcher.py:337](src/agents/query_dispatcher.py))
- Returns `AgentResult(agent="query_dispatcher", answer=formatted_str, verified=True)`

> **Salary question specifically:** maps to `query_type="profile_demographics"` → runs `_Q_PROFILE` → returns `income_range` field from `customers` table.

#### Path B — product_agent (RAG / OpenSearch)
Triggered when intent = `PRODUCT_KNOWLEDGE`.
- `product_agent.run()` ([src/agents/product_agent.py](src/agents/product_agent.py))
- RAG retriever queries OpenSearch for product documents

#### Path C — contract_agent (Neo4j graph)
Triggered when intent = `CONTRACT_QUERY`.
- `contract_agent.run()` ([src/agents/contract_agent.py](src/agents/contract_agent.py))
- Neo4j Cypher queries for contract relationship data

#### Path D — advisory_agent (NBA logic)
Triggered when intent = `ADVISORY`.
- `advisory_agent.run()` ([src/agents/advisory_agent.py](src/agents/advisory_agent.py))

All agents write into `AgentState.agent_results` (list reducer: `operator.add` — parallel safe).

---

### Node ⑤ — aggregator (Sonnet streaming synthesis)
**Route:** all agent nodes → `aggregator`

Merges all `AgentResult` entries, streams a synthesized answer via Sonnet, then runs two safety layers in parallel.

**Classes / functions:**
- `aggregator.run()` ([src/agents/nodes/aggregator.py:59](src/agents/nodes/aggregator.py))
- Emits `agent_result` SSE events for each agent result
- `_build_synthesis_prompt()` ([src/agents/nodes/aggregator.py:36](src/agents/nodes/aggregator.py)) — builds context from `customer_360` + agent results
- `anthropic.AsyncAnthropic.messages.stream()` — model: `claude-sonnet-4-6`, streams tokens
- Each token → `queue.put(("token", token))` → SSE to client
- Post-stream (parallel):
  - `output_guardrail.check()` ([src/safety/output_guardrail.py](src/safety/output_guardrail.py)) — Layer 3
  - `final_nli.check()` ([src/safety/final_nli.py](src/safety/final_nli.py)) — Layer 4 NLI verification
- Emits `done` SSE with `{verified, warning}` payload

---

### Step 5 — SSE stream completes
The `stream_pipeline()` generator in `chat.py` reads `done` or `error` from the queue and closes the response. `asyncio.Task` is awaited for clean shutdown.

---

## Sequence Diagram

```mermaid
sequenceDiagram
    actor Client as Browser / Frontend

    box FastAPI Server
        participant Router   as chat.py<br/>chat()
        participant Auth     as jwt_auth.py<br/>get_current_rep()
        participant Stream   as chat.py<br/>stream_pipeline()
    end

    box LangGraph Pipeline
        participant Orch     as orchestrator.py<br/>run() + _graph
        participant S1       as Node ①<br/>load_session_context
        participant S2       as Node ②<br/>input_guard
        participant S3       as Node ③<br/>intent_rewrite (Haiku)
        participant FanOut   as _fan_out()<br/>Send() dispatcher
        participant QD       as Node ④a<br/>query_dispatcher
        participant PA       as Node ④b<br/>product_agent
        participant AGG      as Node ⑤<br/>aggregator (Sonnet)
    end

    box Data & Cache
        participant Redis    as Redis<br/>redis_client.py
        participant Hasura   as Hasura GraphQL<br/>hasura_client.py
        participant PG       as PostgreSQL
        participant OS       as OpenSearch<br/>opensearch_client.py
        participant Neo4j    as Neo4j<br/>neo4j_client.py
    end

    box External AI
        participant Haiku    as Claude Haiku<br/>(Anthropic API)
        participant Sonnet   as Claude Sonnet<br/>(Anthropic API)
    end

    %% ── Auth ────────────────────────────────────────────────────────────────
    Client->>+Router: POST /chat {customer_id, message, session_id}<br/>Authorization: Bearer <JWT>
    Router->>+Auth: get_current_rep(credentials)
    Auth->>Auth: decode_token() — jose.jwt.decode()
    alt invalid JWT
        Auth-->>Client: HTTP 401
    end
    Auth-->>-Router: {sub: rep_id, name, hasura_claims}

    %% ── SSE opens ───────────────────────────────────────────────────────────
    Router->>+Stream: stream_pipeline(request, rep)
    Stream->>Stream: asyncio.Queue() created
    Router-->>Client: 200 text/event-stream (SSE opens)

    %% ── Orchestrator ────────────────────────────────────────────────────────
    Stream->>+Orch: orchestrator.run(customer_id, message, session_id, ...)
    Orch->>Orch: build AgentState TypedDict<br/>last 10 conversation turns
    Orch->>+Orch: _graph.ainvoke(state, config)

    %% ── Node ① ─────────────────────────────────────────────────────────────
    Orch->>+S1: _load_session_context(state)
    S1->>+Redis: GET session:{session_id}
    alt Cache HIT
        Redis-->>S1: {customer_360, long_term_summaries}
    else Cache MISS
        Redis-->>S1: nil
        S1->>+Hasura: query(_CUSTOMER_QUERY, {id: customer_id})
        Hasura->>+PG: SELECT customers WHERE customer_id=...
        PG-->>-Hasura: {customer_id, full_name, segment, income_range, ...}
        Hasura-->>-S1: {customers: [...]}
        S1->>+OS: search("conversation-summaries", customer_id)
        OS-->>-S1: last 5 summaries
        S1->>Redis: SET session:{session_id} TTL=4h
    end
    S1-->>-Orch: {customer_360: {...}, long_term_summaries: [...]}

    %% ── Node ② ─────────────────────────────────────────────────────────────
    Orch->>+S2: _input_guard(state)
    S2->>S2: input_guardrail.check(message)<br/>regex: PII, SQL injection, off-topic
    alt Blocked
        S2-->>Orch: {input_blocked: true, reason: "..."}
        Orch->>Stream: queue.put("error", reason)
        Orch->>Stream: queue.put("done", "{}")
        Stream-->>Client: SSE: error + done
    end
    S2-->>-Orch: {input_blocked: false}

    %% ── Node ③ ─────────────────────────────────────────────────────────────
    Orch->>+S3: _intent_rewrite(state)
    S3->>+Haiku: messages.create(system=_SYSTEM, user=message+history+summaries)
    Note over S3,Haiku: Classifies intent, resolves pronouns,<br/>converts time expressions → concrete dates
    Haiku-->>-S3: JSON {sub_questions: [{agent, query_type, params, rewritten_query}]}
    S3-->>-Orch: {sub_questions, active_agents, rewritten_query}

    %% ── Fan-out ─────────────────────────────────────────────────────────────
    Orch->>+FanOut: _fan_out(state) — returns list[Send]
    Note over FanOut: One Send() per sub_question → parallel dispatch

    par Path A — TRANSACTION_QUERY
        FanOut->>+QD: Send("_query_dispatcher", branch_state)
        QD->>+Redis: GET query:{cid}:{query_type}:{params_hash}
        alt Query Cache HIT
            Redis-->>QD: cached formatted answer
        else Cache MISS
            Redis-->>QD: nil
            QD->>+Hasura: query(template, {cid, date_from, date_to, ...})
            Hasura->>+PG: SELECT transactions / accounts / loan_accounts / ...
            PG-->>-Hasura: rows
            Hasura-->>-QD: {transactions: [...]} / {accounts: [...]} / ...
            QD->>QD: _fmt_*() → formatted Vietnamese string
            QD->>Redis: SET query:... TTL=30m–24h
        end
        QD->>QD: _log_hasura() @traceable → LangSmith span
        QD-->>-FanOut: AgentResult{agent:"query_dispatcher", verified:true}

    and Path B — PRODUCT_KNOWLEDGE
        FanOut->>+PA: Send("_product_agent", branch_state)
        PA->>OS: vector search — product docs index
        OS-->>PA: top-K chunks
        PA-->>-FanOut: AgentResult{agent:"product"}

    end
    FanOut-->>-Orch: agent_results[] accumulated via operator.add reducer

    %% ── Node ⑤ ─────────────────────────────────────────────────────────────
    Orch->>+AGG: _aggregator(state, config)

    loop each AgentResult
        AGG->>Stream: queue.put("agent_result", {agent, answer[:500], verified})
        Stream-->>Client: SSE: agent_result
    end

    AGG->>Stream: queue.put("thinking", "Đang tổng hợp...")
    Stream-->>Client: SSE: thinking

    AGG->>AGG: _build_synthesis_prompt()<br/>customer_360 + rewritten_query + agent results
    AGG->>+Sonnet: messages.stream(system, user=prompt) max_tokens=2048

    loop streaming tokens
        Sonnet-->>AGG: text token
        AGG->>Stream: queue.put("token", token)
        Stream-->>Client: SSE: token
    end
    Sonnet-->>-AGG: stream complete

    par Safety Layer 3 + Layer 4 (parallel)
        AGG->>AGG: output_guardrail.check(full_answer)
        AGG->>AGG: final_nli.check(full_answer, agent_results)
    end

    AGG->>Stream: queue.put("done", {verified, warning})
    Stream-->>Client: SSE: done {verified: true/false, warning: null/str}
    AGG-->>-Orch: {final_answer, final_verified, final_warning}

    Orch-->>-Stream: pipeline complete
    Stream-->>-Router: async generator exhausted
    Router-->>-Client: SSE stream closed
```

---

## Key Design Decisions

| Concern | Mechanism |
|---|---|
| Auth | JWT validated per-request; Hasura claims embedded for row-level security |
| Session context | Redis cache (4h TTL) — avoids re-fetching Postgres + OpenSearch on every message |
| Query cache | Per-query Redis keys with tiered TTL (30m transactions, 24h demographics) |
| Structured data | GraphQL via Hasura → Postgres — no LLM, `verified=True` always |
| RAG data | OpenSearch vector search → product / contract docs |
| Intent routing | Haiku LLM → fan-out to 1–N agents in parallel via LangGraph `Send()` |
| Synthesis | Sonnet streams tokens directly to SSE queue — no buffering delay |
| Safety | 4 layers: input regex (sync) → output regex → NLI verification (post-stream, parallel) |
| Observability | LangSmith `@traceable` spans on Hasura calls; LangChainTracer on full graph |
