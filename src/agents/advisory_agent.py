"""
AdvisoryAgent: customer profile analysis → NBA logic → sales script → Sonnet → NLI.
Recommends the next best product and provides a conversation guide for the rep.
"""
import anthropic
from src.agents.state import AgentState, AgentResult
from src.config import get_settings
from src.rag import retriever
from src.safety import nli_checker

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


_SYSTEM = """Bạn là chuyên gia tư vấn tài chính cá nhân của Techcombank.
Nhiệm vụ: phân tích hồ sơ khách hàng và đề xuất sản phẩm phù hợp nhất (Next Best Action).

Quy tắc:
- Đề xuất phải phù hợp với phân khúc và thu nhập của khách hàng.
- Chỉ đề xuất sản phẩm có trong danh mục Techcombank.
- Cung cấp 2-3 điểm mở đầu cuộc trò chuyện (conversation starter) cho chuyên viên.
- Giải thích TẠI SAO khách hàng này phù hợp với sản phẩm được đề xuất.
- Trả lời bằng tiếng Việt, thực tế và thuyết phục."""

# NBA rules: segment → recommended products if not already held
_NBA_RULES: dict[str, list[str]] = {
    "Standard": ["CASA", "DEBIT"],
    "Silver":   ["CREDIT_GOLD", "TERM_DEPOSIT", "PERSONAL_ACCIDENT"],
    "Gold":     ["BANCASSURANCE", "CREDIT_PLATINUM", "CERTIFICATE_OF_DEPOSIT", "TRAVEL_INSURANCE"],
    "Platinum": ["BANCASSURANCE", "BUSINESS_LENDING", "VIP_PRIORITY", "NON_LIFE_INSURANCE"],
    "Elite":    ["BANCASSURANCE", "BUSINESS_LENDING", "VIP_PRIORITY", "CERTIFICATE_OF_DEPOSIT"],
}


def _suggest_nba(customer: dict) -> list[str]:
    segment      = customer.get("segment", "Standard")
    held_codes   = {p["product_code"] for p in customer.get("products_held", [])}
    candidates   = _NBA_RULES.get(segment, [])
    return [p for p in candidates if p not in held_codes][:3]   # top 3 gaps


def _format_profile(customer: dict, nba: list[str]) -> str:
    segment      = customer.get("segment", "N/A")
    credit_score = customer.get("credit_score", "N/A")
    loyalty      = customer.get("loyalty_points", 0)
    income       = customer.get("income_range", "N/A")
    occupation   = customer.get("occupation", "N/A")
    city         = customer.get("city", "N/A")
    since        = customer.get("relationship_since", "N/A")
    held         = [p["product_code"] for p in customer.get("products_held", [])]

    # Recent spending pattern
    txns = customer.get("transactions", [])[:10]
    categories = {}
    for t in txns:
        cat = t.get("merchant_category", "OTHER")
        categories[cat] = categories.get(cat, 0) + abs(t.get("amount", 0))
    top_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:3]
    spending_summary = ", ".join(f"{c}: {a:,.0f} VND" for c, a in top_cats) or "N/A"

    # Last session memory
    memory = customer.get("memory", [])
    last_summary = memory[0]["summary"] if memory else "Chưa có lịch sử tư vấn"

    return f"""HỒ SƠ KHÁCH HÀNG:
- Phân khúc: {segment} | Thu nhập: {income} | Nghề nghiệp: {occupation}
- Thành phố: {city} | Khách hàng từ: {since}
- Credit score: {credit_score} | Điểm tích lũy: {loyalty:,}
- Sản phẩm đang dùng: {', '.join(held) or 'Chưa có'}
- Chi tiêu nổi bật (gần đây): {spending_summary}
- Lịch sử tư vấn: {last_summary}

ĐỀ XUẤT NBA (sản phẩm chưa có, phù hợp với phân khúc):
{chr(10).join(f'- {p}' for p in nba) if nba else 'Khách hàng đã có đủ sản phẩm cơ bản'}"""


async def run(state: AgentState) -> dict:
    query    = state.get("rewritten_query") or state["message"]
    customer = state.get("customer_360", {})

    nba = _suggest_nba(customer)

    # Retrieve product info for NBA candidates
    nba_query = f"tư vấn sản phẩm {' '.join(nba)} cho khách hàng {customer.get('segment', '')}"
    hits = await retriever.aretrieve(query=nba_query, index="product-docs", top_n_final=3)
    product_context = retriever.format_chunks(hits) if hits else ""

    profile_text = _format_profile(customer, nba)

    prompt = f"""{profile_text}

{"TÀI LIỆU SẢN PHẨM ĐỀ XUẤT:" + chr(10) + product_context if product_context else ""}

YÊU CẦU TƯ VẤN: {query}

Hãy đưa ra đề xuất sản phẩm và kịch bản tư vấn cho chuyên viên."""

    resp = await _get_client().messages.create(
        model=get_settings().anthropic_sonnet_model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = resp.content[0].text.strip()

    chunk_texts = [profile_text] + [h["_source"]["text"] for h in hits]
    verified, warning = nli_checker.check(answer, chunk_texts)

    result: AgentResult = {
        "agent":    "advisory",
        "answer":   answer,
        "sources":  nba,
        "verified": verified,
        "warning":  warning,
    }
    return {"agent_results": [result]}
