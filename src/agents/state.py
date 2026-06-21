import operator
from typing import Annotated, Any, Optional, TypedDict


class AgentResult(TypedDict):
    agent:    str          # "product" | "contract" | "advisory"
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

    # ── Short-term memory: conversation turns this session (from frontend) ───
    # [{role: "rep"|"agent", content: str}, ...]  — last 10 turns max
    conversation_history: list[dict]

    # ── Long-term memory + customer 360: loaded from Redis / Hasura + OS ─────
    # Populated by Orchestrator node ① (Load Session Context)
    customer_360:         dict       # full profile from Hasura
    long_term_summaries:  list[dict] # last 5 session summaries from OpenSearch

    # ── After intent rewrite (Node 2) ────────────────────────────────────────
    intent:          str            # "product" | "contract" | "advisory" | "multi"
    rewritten_query: str
    sub_questions:   list[str]
    active_agents:   list[str]      # agents to invoke e.g. ["product", "contract"]

    # ── Agent results — list reducer so parallel agents can each append ──────
    agent_results: Annotated[list[AgentResult], operator.add]

    # ── After aggregator / synthesis ─────────────────────────────────────────
    final_answer:    str
    final_verified:  bool
    final_warning:   Optional[str]

    # ── Safety ───────────────────────────────────────────────────────────────
    input_blocked:       bool
    input_block_reason:  Optional[str]
