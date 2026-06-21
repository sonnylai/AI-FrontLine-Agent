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

    # ── After intent rewrite (Node 1) ────────────────────────────────────────
    intent:          str            # "product" | "contract" | "advisory" | "multi"
    rewritten_query: str
    sub_questions:   list[str]
    active_agents:   list[str]      # agents to invoke e.g. ["product", "contract"]

    # ── After query dispatcher (Node 2) ──────────────────────────────────────
    customer_360: dict              # full profile from Hasura

    # ── Agent results — list reducer so parallel agents can each append ──────
    agent_results: Annotated[list[AgentResult], operator.add]

    # ── After aggregator / synthesis (Node 3) ────────────────────────────────
    final_answer: str
    final_verified: bool
    final_warning:  Optional[str]

    # ── Safety ───────────────────────────────────────────────────────────────
    input_blocked:       bool
    input_block_reason:  Optional[str]
