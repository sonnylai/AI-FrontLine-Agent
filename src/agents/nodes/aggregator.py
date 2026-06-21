"""
Node — Aggregator + Final Synthesis.
Merges parallel agent results, streams Sonnet answer, then runs
Layer 3 (Output Guardrail) and Layer 4 (Final NLI) in parallel post-stream.
Tokens are written to stream_queue (passed via RunnableConfig).
"""
import asyncio
import json
import anthropic
from langgraph.types import RunnableConfig

from src.agents.state import AgentState
from src.config import get_settings
from src.safety import final_nli, output_guardrail

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


_SYSTEM = """Bạn là trợ lý tư vấn tài chính cấp cao của Techcombank.
Nhiệm vụ: tổng hợp thông tin từ nhiều chuyên gia và đưa ra câu trả lời hoàn chỉnh cho chuyên viên.

Quy tắc:
- Tổng hợp thông tin một cách mạch lạc, không lặp lại.
- Ưu tiên thông tin đã được xác minh (verified).
- Nếu có cảnh báo từ agent, đề cập nhẹ nhàng và khuyên kiểm tra lại.
- Trả lời bằng tiếng Việt, rõ ràng và hành động được ngay."""


def _build_synthesis_prompt(state: AgentState) -> str:
    customer = state.get("customer_360", {})
    name     = customer.get("full_name", "Khách hàng")
    segment  = customer.get("segment", "N/A")
    question = state.get("rewritten_query") or state["message"]

    results = state.get("agent_results", [])
    agent_block = ""
    for r in results:
        badge = "✅" if r["verified"] else "⚠️"
        agent_block += f"\n\n[{r['agent'].upper()} {badge}]\n{r['answer']}"
        if r.get("warning"):
            agent_block += f"\n⚠️ Lưu ý: {r['warning']}"

    return f"""Câu hỏi: {question}
Khách hàng: {name} (Phân khúc: {segment})

KẾT QUẢ TỪ CÁC CHUYÊN GIA:
{agent_block}

Hãy tổng hợp thành câu trả lời hoàn chỉnh cho chuyên viên."""


async def run(state: AgentState, config: RunnableConfig) -> dict:
    queue: asyncio.Queue = config["configurable"]["stream_queue"]
    results = state.get("agent_results", [])

    # Emit each agent result before synthesis
    for r in results:
        await queue.put(("agent_result", json.dumps({
            "agent":    r["agent"],
            "answer":   r["answer"][:500],
            "verified": r["verified"],
            "warning":  r.get("warning"),
            "sources":  r.get("sources", []),
        }, ensure_ascii=False)))

    await queue.put(("thinking", "Đang tổng hợp câu trả lời..."))

    # Stream final synthesis
    full_answer = ""
    prompt = _build_synthesis_prompt(state)

    async with _get_client().messages.stream(
        model=get_settings().anthropic_sonnet_model,
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for token in stream.text_stream:
            full_answer += token
            await queue.put(("token", token))

    # Layer 3 + Layer 4 run in parallel post-stream (do not block tokens)
    (og_passed, og_warning), (nli_verified, nli_warning) = await asyncio.gather(
        output_guardrail.check(full_answer),
        final_nli.check(full_answer, results),
    )

    # Combine verdicts: both must pass for overall verified
    overall_verified = og_passed and nli_verified
    overall_warning  = og_warning or nli_warning

    await queue.put(("done", json.dumps({
        "verified": overall_verified,
        "warning":  overall_warning,
    }, ensure_ascii=False)))

    return {
        "final_answer":   full_answer,
        "final_verified": overall_verified,
        "final_warning":  overall_warning,
    }
