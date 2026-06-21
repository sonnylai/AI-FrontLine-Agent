"""
Node 1 — IntentRewrite: Haiku classifies intent, rewrites query, decides fan-out.
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
- "product": câu hỏi về đặc điểm, phí, điều kiện, quyền lợi của sản phẩm ngân hàng
- "contract": câu hỏi về hợp đồng cụ thể, điều khoản, bồi thường, tình trạng hợp đồng của khách hàng
- "advisory": câu hỏi về tư vấn, đề xuất sản phẩm phù hợp, chiến lược bán hàng cho khách hàng
- "multi": câu hỏi kết hợp nhiều loại trên

Agents tương ứng: product → ["product"], contract → ["contract"], advisory → ["advisory"],
multi → tập hợp các agent cần thiết.

Trả về CHÍNH XÁC JSON sau, không giải thích:
{
  "intent": "<product|contract|advisory|multi>",
  "active_agents": ["<agent1>", ...],
  "rewritten_query": "<câu hỏi được viết lại rõ ràng hơn>",
  "sub_questions": ["<câu hỏi con 1>", ...]
}"""


async def run(state: AgentState) -> dict:
    message = state["message"]
    customer_id = state.get("customer_id", "")

    prompt = f"""Câu hỏi của chuyên viên (về khách hàng {customer_id}): {message}

Phân loại và viết lại câu hỏi."""

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
        # Fallback: treat as product question if parsing fails
        data = {
            "intent": "product",
            "active_agents": ["product"],
            "rewritten_query": message,
            "sub_questions": [message],
        }

    return {
        "intent":          data.get("intent", "product"),
        "active_agents":   data.get("active_agents", ["product"]),
        "rewritten_query": data.get("rewritten_query", message),
        "sub_questions":   data.get("sub_questions", [message]),
    }
