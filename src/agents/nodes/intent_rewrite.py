"""
Node ③ — IntentRewriteNode (Haiku).
Single LLM call that:
  1. Resolves pronouns and vague references using conversation history + long-term summaries
  2. Classifies intent per sub-question
  3. Resolves time expressions to concrete dates (e.g. "3 tháng qua" → date_from/date_to)
  4. Outputs a structured sub_questions list — one entry per agent to invoke

Output drives the fan-out: each sub_question becomes one Send() in the graph.
See MEMORY_SCHEMA.md §1d for the full sub_questions schema.
"""
import json
from datetime import date
import anthropic
from src.agents.state import AgentState
from src.config import get_settings

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


_SYSTEM = """Bạn là bộ phân loại câu hỏi cho hệ thống AI ngân hàng Techcombank.
Hôm nay: {today}

Nhiệm vụ: phân tích câu hỏi → trả về danh sách sub_questions (JSON).

INTENT và AGENT tương ứng:
- TRANSACTION_QUERY  → agent: "query_dispatcher"
  Dùng khi hỏi về dữ liệu CÓ CẤU TRÚC của khách hàng trong Postgres:
  thu nhập/lương, sản phẩm đang dùng, chi tiêu, số dư, dư nợ, tiền gửi, bảo hiểm.

- PRODUCT_KNOWLEDGE  → agent: "product"
  Dùng khi hỏi về đặc điểm SẢN PHẨM ngân hàng: phí, lãi suất, điều kiện, quyền lợi.
  (Thông tin này trong OpenSearch, KHÔNG phải Postgres)

- CONTRACT_QUERY     → agent: "contract"
  Dùng khi hỏi về hợp đồng cụ thể của khách hàng: điều khoản, bồi thường, tình trạng.

- ADVISORY           → agent: "advisory"
  Dùng khi hỏi về tư vấn, đề xuất sản phẩm phù hợp, chiến lược bán hàng NBA.

query_type (chỉ dùng cho TRANSACTION_QUERY):
- profile_demographics      : thu nhập, nghề nghiệp, KYC, credit score, thành phố
- product_portfolio_summary : sản phẩm đang dùng, danh mục hợp đồng
- aggregate_by_category     : chi tiêu theo danh mục (params: date_from, date_to)
- aggregate_by_merchant     : chi tiêu theo merchant (params: date_from, date_to, merchant_category)
- transaction_count_by_period: số giao dịch (params: date_from, date_to)
- casa_balance_summary      : số dư tài khoản thanh toán/tiết kiệm
- loan_balance_remaining    : dư nợ vay còn lại
- term_deposit_list         : danh sách tiền gửi có kỳ hạn
- insurance_contract_status : tình trạng hợp đồng bảo hiểm
- segment_gap_analysis      : phân tích khoảng cách phân khúc, NBA gap

QUAN TRỌNG:
- Dùng lịch sử hội thoại để giải nghĩa đại từ mơ hồ và câu hỏi ngắn.
- Chuyển biểu thức thời gian thành ngày cụ thể dựa vào hôm nay ({today}):
  "tháng này" → date_from: ngày đầu tháng, date_to: hôm nay
  "3 tháng qua" → date_from: 90 ngày trước hôm nay, date_to: hôm nay
  "năm nay" → date_from: YYYY-01-01, date_to: hôm nay
  Không đề cập thời gian → default: date_from 90 ngày trước, date_to hôm nay
- Viết rewritten_query tự đầy đủ, thay thế đại từ bằng tên/mã cụ thể.

Trả về CHÍNH XÁC JSON sau, không giải thích thêm:
{
  "sub_questions": [
    {
      "id": "sq1",
      "intent": "<TRANSACTION_QUERY|PRODUCT_KNOWLEDGE|CONTRACT_QUERY|ADVISORY>",
      "agent": "<query_dispatcher|product|contract|advisory>",
      "query_type": "<template hoặc empty string nếu không phải TRANSACTION_QUERY>",
      "params": {<các params cụ thể hoặc {} nếu không cần>},
      "rewritten_query": "<câu hỏi tự đầy đủ>"
    }
  ]
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
    lines = ["LỊCH SỬ TƯ VẤN TRƯỚC:"]
    for s in summaries[:3]:
        lines.append(f"- {s.get('session_date', '')}: {s.get('summary', '')}")
    return "\n".join(lines)


async def run(state: AgentState) -> dict:
    today       = date.today().isoformat()
    message     = state["message"]
    customer_id = state.get("customer_id", "")
    history     = state.get("conversation_history", [])
    summaries   = state.get("long_term_summaries", [])

    context_block = "\n\n".join(filter(None, [
        _format_history(history),
        _format_summaries(summaries),
    ]))

    prompt = (
        f"{context_block}\n\n" if context_block else ""
    ) + f"Câu hỏi (về khách hàng {customer_id}): {message}"

    resp = await _get_client().messages.create(
        model=get_settings().anthropic_haiku_model,
        max_tokens=1024,
        system=_SYSTEM.replace("{today}", today),
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resp.content[0].text.strip().strip("`")
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        data = json.loads(raw)
        sub_questions = data.get("sub_questions", [])
        if not sub_questions:
            raise ValueError("empty sub_questions")
    except Exception:
        sub_questions = [{
            "id":              "sq1",
            "intent":          "PRODUCT_KNOWLEDGE",
            "agent":           "product",
            "query_type":      "",
            "params":          {},
            "rewritten_query": message,
        }]

    # Derive active_agents and primary rewritten_query from sub_questions
    active_agents   = [sq["agent"] for sq in sub_questions]
    rewritten_query = sub_questions[0]["rewritten_query"] if sub_questions else message

    return {
        "sub_questions":   sub_questions,
        "active_agents":   active_agents,
        "rewritten_query": rewritten_query,
        "query_type":      "",   # set per fan-out branch
        "query_params":    {},   # set per fan-out branch
    }
