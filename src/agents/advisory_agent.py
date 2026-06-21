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
    segment    = customer.get("segment", "Standard")
    held_codes = set(customer.get("products_held", []))   # already list[str]
    candidates = _NBA_RULES.get(segment, [])
    return [p for p in candidates if p not in held_codes][:3]


def _format_profile(customer: dict, nba: list[str], summaries: list[dict]) -> str:
    segment    = customer.get("segment", "N/A")
    income     = customer.get("income_range", "N/A")
    occupation = customer.get("occupation", "N/A")
    city       = customer.get("city", "N/A")
    held       = customer.get("products_held", [])   # list[str]

    # Last session summary from long-term memory (passed in separately)
    last_summary = summaries[0]["summary"] if summaries else "Chưa có lịch sử tư vấn"

    return f"""HỒ SƠ KHÁCH HÀNG:
- Phân khúc: {segment} | Thu nhập: {income} | Nghề nghiệp: {occupation}
- Thành phố: {city}
- Sản phẩm đang dùng: {', '.join(held) or 'Chưa có'}
- Lịch sử tư vấn gần nhất: {last_summary}

ĐỀ XUẤT NBA (sản phẩm chưa có, phù hợp với phân khúc):
{chr(10).join(f'- {p}' for p in nba) if nba else 'Khách hàng đã có đủ sản phẩm cơ bản'}"""


async def run(state: AgentState) -> dict:
    query    = state.get("rewritten_query") or state["message"]
    customer = state.get("customer_360", {})

    summaries = state.get("long_term_summaries", [])
    nba       = _suggest_nba(customer)

    # Retrieve product info for NBA candidates
    nba_query = f"tư vấn sản phẩm {' '.join(nba)} cho khách hàng {customer.get('segment', '')}"
    hits = await retriever.aretrieve(query=nba_query, index="product-docs", top_n_final=3)
    product_context = retriever.format_chunks(hits) if hits else ""

    profile_text = _format_profile(customer, nba, summaries)

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
    verified, warning = nli_checker.check(answer, chunk_texts, agent="advisory")

    result: AgentResult = {
        "agent":    "advisory",
        "answer":   answer,
        "sources":  nba,
        "verified": verified,
        "warning":  warning,
    }
    return {"agent_results": [result]}
