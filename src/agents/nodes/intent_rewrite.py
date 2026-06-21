"""
Node ③ — IntentRewrite (Haiku).
Uses short-term conversation history + long-term summaries to:
  1. Resolve pronouns and vague references ("cái đó", "tại sao không?")
  2. Classify intent
  3. Rewrite query to be fully self-contained
  4. Decide which agents to invoke
"""
import json
import anthropic
from src.agents.state import AgentState
from src.config import get_settings

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


_SYSTEM = """Bạn là trợ lý phân loại câu hỏi cho hệ thống ngân hàng Techcombank.
Nhiệm vụ: phân tích câu hỏi của chuyên viên tư vấn và trả về JSON.

Các loại intent:
- "product": câu hỏi về đặc điểm, phí, điều kiện, quyền lợi sản phẩm ngân hàng
- "contract": câu hỏi về hợp đồng cụ thể, điều khoản, bồi thường, tình trạng của khách hàng
- "advisory": câu hỏi về tư vấn, đề xuất sản phẩm phù hợp, chiến lược bán hàng
- "multi": kết hợp nhiều loại trên

Agents: product → ["product"], contract → ["contract"], advisory → ["advisory"],
multi → tập hợp các agent cần thiết.

QUAN TRỌNG: Nếu có lịch sử hội thoại, hãy dùng nó để:
- Giải nghĩa đại từ mơ hồ ("cái đó", "quyền lợi đó", "sản phẩm này")
- Hiểu câu hỏi ngắn ("tại sao không?", "còn gói khác?")
- Viết lại câu hỏi đầy đủ, không phụ thuộc lịch sử

Trả về CHÍNH XÁC JSON sau, không giải thích:
{
  "intent": "<product|contract|advisory|multi>",
  "active_agents": ["<agent1>", ...],
  "rewritten_query": "<câu hỏi tự đầy đủ, không cần ngữ cảnh>",
  "sub_questions": ["<câu hỏi con 1>", ...]
}"""


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["LỊCH SỬ HỘI THOẠI (gần nhất):"]
    for turn in history[-10:]:
        role = "Chuyên viên" if turn.get("role") == "rep" else "AI"
        lines.append(f"[{role}]: {turn.get('content', '')[:200]}")
    return "\n".join(lines)


def _format_summaries(summaries: list[dict]) -> str:
    if not summaries:
        return ""
    lines = ["LỊCH SỬ TƯ VẤN TRƯỚC (tóm tắt):"]
    for s in summaries[:3]:
        lines.append(f"- {s.get('session_date', '')}: {s.get('summary', '')}")
        if s.get("key_concerns"):
            lines.append(f"  Mối quan tâm: {', '.join(s['key_concerns'])}")
    return "\n".join(lines)


async def run(state: AgentState) -> dict:
    message   = state["message"]
    history   = state.get("conversation_history", [])
    summaries = state.get("long_term_summaries", [])
    customer_id = state.get("customer_id", "")

    history_block   = _format_history(history)
    summaries_block = _format_summaries(summaries)
    context_block   = "\n\n".join(filter(None, [history_block, summaries_block]))

    prompt = f"""{context_block + chr(10) + chr(10) if context_block else ""}Câu hỏi hiện tại (về khách hàng {customer_id}): {message}

Phân loại và viết lại câu hỏi thành dạng tự đầy đủ."""

    resp = await _get_client().messages.create(
        model=get_settings().anthropic_haiku_model,
        max_tokens=512,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resp.content[0].text.strip().strip("`")
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        data = json.loads(raw)
    except Exception:
        data = {
            "intent":          "product",
            "active_agents":   ["product"],
            "rewritten_query": message,
            "sub_questions":   [message],
        }

    return {
        "intent":          data.get("intent", "product"),
        "active_agents":   data.get("active_agents", ["product"]),
        "rewritten_query": data.get("rewritten_query", message),
        "sub_questions":   data.get("sub_questions", [message]),
    }
