"""
Orchestrator — LangGraph StateGraph that wires all nodes into the agent pipeline.

Flow:
  START → intent_rewrite → query_dispatcher → [router]
    → product_agent / contract_agent / advisory_agent  (parallel via Send)
    → aggregator (fan-in + streaming synthesis)
  → END
"""
import asyncio
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send, RunnableConfig

from src.agents.state import AgentState
from src.agents.nodes import intent_rewrite, query_dispatcher, aggregator
from src.agents import product_agent, contract_agent, advisory_agent
from src.safety import input_guardrail


# ── Node wrappers ─────────────────────────────────────────────────────────────

async def _input_guard(state: AgentState) -> dict:
    blocked, reason = input_guardrail.check(state["message"])
    return {"input_blocked": blocked, "input_block_reason": reason}


async def _intent_rewrite(state: AgentState) -> dict:
    return await intent_rewrite.run(state)


async def _query_dispatcher(state: AgentState) -> dict:
    return await query_dispatcher.run(state)


async def _product_agent(state: AgentState) -> dict:
    return await product_agent.run(state)


async def _contract_agent(state: AgentState) -> dict:
    return await contract_agent.run(state)


async def _advisory_agent(state: AgentState) -> dict:
    return await advisory_agent.run(state)


async def _aggregator(state: AgentState, config: RunnableConfig) -> dict:
    return await aggregator.run(state, config)


# ── Conditional routing ────────────────────────────────────────────────────────

def _route_after_guard(state: AgentState) -> str:
    if state.get("input_blocked"):
        return "blocked"
    return "intent_rewrite"


async def _block_and_done(state: AgentState, config: RunnableConfig) -> dict:
    """Short-circuit path when input guardrail fires."""
    queue: asyncio.Queue = config["configurable"]["stream_queue"]
    reason = state.get("input_block_reason", "Câu hỏi không hợp lệ.")
    await queue.put(("error", reason))
    await queue.put(("done", "{}"))
    return {"final_answer": reason, "final_verified": False, "final_warning": reason}


def _fan_out(state: AgentState) -> list[Send] | str:
    """
    After query_dispatcher: dispatch to 1 or more agents in parallel.
    LangGraph Send runs each target node with the current state and collects
    results via the `agent_results` list reducer.
    """
    agents = state.get("active_agents", ["product"])
    node_map = {
        "product":  "_product_agent",
        "contract": "_contract_agent",
        "advisory": "_advisory_agent",
    }
    sends = [Send(node_map[a], state) for a in agents if a in node_map]
    return sends if sends else "aggregator"


# ── Build graph ────────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("input_guard",       _input_guard)
    g.add_node("blocked",           _block_and_done)
    g.add_node("intent_rewrite",    _intent_rewrite)
    g.add_node("query_dispatcher",  _query_dispatcher)
    g.add_node("_product_agent",    _product_agent)
    g.add_node("_contract_agent",   _contract_agent)
    g.add_node("_advisory_agent",   _advisory_agent)
    g.add_node("aggregator",        _aggregator)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges(
        "input_guard",
        _route_after_guard,
        {"blocked": "blocked", "intent_rewrite": "intent_rewrite"},
    )
    g.add_edge("blocked", END)
    g.add_edge("intent_rewrite", "query_dispatcher")
    g.add_conditional_edges(
        "query_dispatcher",
        _fan_out,
        ["_product_agent", "_contract_agent", "_advisory_agent", "aggregator"],
    )
    # All agent branches converge at aggregator
    g.add_edge("_product_agent",   "aggregator")
    g.add_edge("_contract_agent",  "aggregator")
    g.add_edge("_advisory_agent",  "aggregator")
    g.add_edge("aggregator", END)

    return g


_graph = _build_graph().compile()


# ── Public entry point ────────────────────────────────────────────────────────

async def run(
    *,
    customer_id: str,
    rep_id:      str,
    message:     str,
    session_id:  str,
    stream_queue: asyncio.Queue,
) -> None:
    """
    Execute the full agent pipeline.
    Tokens and events are put into stream_queue for the SSE endpoint to read.
    """
    initial_state: AgentState = {
        "rep_id":            rep_id,
        "customer_id":       customer_id,
        "message":           message,
        "session_id":        session_id,
        "intent":            "",
        "rewritten_query":   "",
        "sub_questions":     [],
        "active_agents":     [],
        "customer_360":      {},
        "agent_results":     [],
        "final_answer":      "",
        "final_verified":    False,
        "final_warning":     None,
        "input_blocked":     False,
        "input_block_reason": None,
    }

    config: RunnableConfig = {
        "configurable": {"stream_queue": stream_queue},
        "recursion_limit": 25,
    }

    await _graph.ainvoke(initial_state, config=config)
