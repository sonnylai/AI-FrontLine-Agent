"""
Orchestrator — LangGraph StateGraph.

Node order:
  ① load_session_context  — Redis hit → inject; miss → Hasura + OpenSearch → cache
  ② input_guard           — sync rule-based block
  ③ intent_rewrite        — Haiku: classify + rewrite using conversation history
  ④ fan-out               — Send API dispatches 1-N agents in parallel
  ⑤ aggregator            — merge results + Sonnet streaming synthesis
"""
import asyncio
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send, RunnableConfig

from src.agents.state import AgentState
from src.agents.nodes import intent_rewrite, aggregator
from src.agents import product_agent, contract_agent, advisory_agent
from src.cache import session_store
from src.safety import input_guardrail


# ── Node ① — Load Session Context ────────────────────────────────────────────

async def _load_session_context(state: AgentState) -> dict:
    """
    Orchestrator node ①.
    Redis HIT  → returns cached assembled context (customer_360 + summaries).
    Redis MISS → loads from Hasura + OpenSearch, caches, returns.
    """
    context = await session_store.load(state["session_id"], state["customer_id"])
    return {
        "customer_360":        context.get("customer_360", {}),
        "long_term_summaries": context.get("long_term_summaries", []),
    }


# ── Node ② — Input Guardrail ──────────────────────────────────────────────────

async def _input_guard(state: AgentState) -> dict:
    blocked, reason = input_guardrail.check(state["message"])
    return {"input_blocked": blocked, "input_block_reason": reason}


# ── Node ③ — Intent Rewrite ───────────────────────────────────────────────────

async def _intent_rewrite(state: AgentState) -> dict:
    return await intent_rewrite.run(state)


# ── Parallel agent nodes ──────────────────────────────────────────────────────

async def _product_agent(state: AgentState) -> dict:
    return await product_agent.run(state)


async def _contract_agent(state: AgentState) -> dict:
    return await contract_agent.run(state)


async def _advisory_agent(state: AgentState) -> dict:
    return await advisory_agent.run(state)


# ── Node ⑤ — Aggregator ──────────────────────────────────────────────────────

async def _aggregator(state: AgentState, config: RunnableConfig) -> dict:
    return await aggregator.run(state, config)


# ── Blocked short-circuit ─────────────────────────────────────────────────────

async def _block_and_done(state: AgentState, config: RunnableConfig) -> dict:
    queue: asyncio.Queue = config["configurable"]["stream_queue"]
    reason = state.get("input_block_reason", "Câu hỏi không hợp lệ.")
    await queue.put(("error", reason))
    await queue.put(("done", "{}"))
    return {"final_answer": reason, "final_verified": False, "final_warning": reason}


# ── Routing functions ─────────────────────────────────────────────────────────

def _route_after_guard(state: AgentState) -> str:
    return "blocked" if state.get("input_blocked") else "intent_rewrite"


def _fan_out(state: AgentState) -> list[Send] | str:
    node_map = {
        "product":  "_product_agent",
        "contract": "_contract_agent",
        "advisory": "_advisory_agent",
    }
    agents = state.get("active_agents", ["product"])
    sends = [Send(node_map[a], state) for a in agents if a in node_map]
    return sends if sends else "aggregator"


# ── Build graph ───────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("load_session_context", _load_session_context)
    g.add_node("input_guard",          _input_guard)
    g.add_node("blocked",              _block_and_done)
    g.add_node("intent_rewrite",       _intent_rewrite)
    g.add_node("_product_agent",       _product_agent)
    g.add_node("_contract_agent",      _contract_agent)
    g.add_node("_advisory_agent",      _advisory_agent)
    g.add_node("aggregator",           _aggregator)

    g.add_edge(START, "load_session_context")
    g.add_edge("load_session_context", "input_guard")
    g.add_conditional_edges(
        "input_guard",
        _route_after_guard,
        {"blocked": "blocked", "intent_rewrite": "intent_rewrite"},
    )
    g.add_edge("blocked", END)
    g.add_conditional_edges(
        "intent_rewrite",
        _fan_out,
        ["_product_agent", "_contract_agent", "_advisory_agent", "aggregator"],
    )
    g.add_edge("_product_agent",  "aggregator")
    g.add_edge("_contract_agent", "aggregator")
    g.add_edge("_advisory_agent", "aggregator")
    g.add_edge("aggregator", END)

    return g


_graph = _build_graph().compile()


# ── Public entry point ────────────────────────────────────────────────────────

async def run(
    *,
    customer_id:          str,
    rep_id:               str,
    message:              str,
    session_id:           str,
    conversation_history: list[dict],
    stream_queue:         asyncio.Queue,
) -> None:
    initial_state: AgentState = {
        "rep_id":               rep_id,
        "customer_id":          customer_id,
        "message":              message,
        "session_id":           session_id,
        "conversation_history": conversation_history[-10:],  # last 10 turns max
        "customer_360":         {},
        "long_term_summaries":  [],
        "intent":               "",
        "rewritten_query":      "",
        "sub_questions":        [],
        "active_agents":        [],
        "agent_results":        [],
        "final_answer":         "",
        "final_verified":       False,
        "final_warning":        None,
        "input_blocked":        False,
        "input_block_reason":   None,
    }

    config: RunnableConfig = {
        "configurable": {"stream_queue": stream_queue},
        "recursion_limit": 25,
    }

    await _graph.ainvoke(initial_state, config=config)
