import operator
from typing import Annotated, Optional, TypedDict


class AgentResult(TypedDict):
    agent:    str          # "query_dispatcher" | "product" | "contract" | "advisory"
    answer:   str
    sources:  list[str]
    verified: bool
    warning:  Optional[str]


class AgentState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────────────
    rep_id:      str
    customer_id: str
    message:     str
    session_id:  str

    # ── Short-term: conversation turns this session (from frontend)
    # [{role: "rep"|"agent", content: str}]  — last 10 turns, discarded after IntentRewrite
    conversation_history: list[dict]

    # ── Session context: loaded by node ① from Redis (Hasura + OpenSearch on miss)
    # customer_360: MINIMAL 8 fields only — see MEMORY_SCHEMA.md §1b
    #   {customer_id, full_name, segment, kyc_status, income_range, occupation, city, products_held}
    #   products_held → list[str] of codes e.g. ["BANCASSURANCE", "CASA"]
    #   Transactions, balances, contracts are NOT here — QueryDispatcher fetches on-demand.
    customer_360:        dict
    long_term_summaries: list[dict]  # last 3–5 summaries from OpenSearch — see MEMORY_SCHEMA.md §1c

    # ── After IntentRewriteNode ───────────────────────────────────────────────
    # sub_questions: one structured entry per agent to invoke — see MEMORY_SCHEMA.md §1d
    #   Each: {id, intent, agent, query_type, params, rewritten_query}
    sub_questions:   list[dict]
    active_agents:   list[str]   # derived from sub_questions for LangGraph routing
    rewritten_query: str         # primary sub-question rewritten query
    query_type:      str         # set per fan-out branch for QueryDispatcher
    query_params:    dict        # resolved params per branch (date_from, date_to, etc.)

    # ── Agent results — reducer: parallel branches each append one entry ──────
    agent_results: Annotated[list[AgentResult], operator.add]

    # ── After Aggregator / synthesis ─────────────────────────────────────────
    final_answer:   str
    final_verified: bool
    final_warning:  Optional[str]

    # ── Safety ───────────────────────────────────────────────────────────────
    input_blocked:      bool
    input_block_reason: Optional[str]
