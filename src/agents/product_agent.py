"""
ProductKnowledgeAgent: RAG retrieval → Sonnet reasoning → per-agent NLI.
Answers questions about product features, fees, eligibility, benefits.
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


_SYSTEM = """Bạn là chuyên gia sản phẩm tài chính của Techcombank.
Nhiệm vụ: trả lời câu hỏi về sản phẩm dựa CHÍNH XÁC vào tài liệu được cung cấp.

Quy tắc:
- Chỉ sử dụng thông tin có trong [Nguồn]. Không bịa đặt số liệu.
- Nếu thông tin không có trong nguồn, nói rõ "Tôi không có thông tin về vấn đề này".
- Trả lời bằng tiếng Việt, ngắn gọn và chuyên nghiệp.
- Trích dẫn nguồn cụ thể khi đề cập đến điều khoản hay số liệu quan trọng."""


def _build_prompt(query: str, context: str, customer: dict) -> str:
    segment  = customer.get("segment", "N/A")
    products = ", ".join(p["product_code"] for p in customer.get("products_held", []))
    return f"""THÔNG TIN KHÁCH HÀNG:
- Phân khúc: {segment}
- Sản phẩm đang sử dụng: {products}

TÀI LIỆU SẢN PHẨM:
{context}

CÂU HỎI: {query}

Hãy trả lời dựa trên tài liệu trên."""


async def run(state: AgentState) -> dict:
    query    = state.get("rewritten_query") or state["message"]
    customer = state.get("customer_360", {})

    # RAG: retrieve top-5 relevant product chunks
    hits = await retriever.aretrieve(query=query, index="product-docs", top_n_final=5)
    context = retriever.format_chunks(hits)
    source_ids = [h["_id"] for h in hits]

    # Sonnet reasoning
    resp = await _get_client().messages.create(
        model=get_settings().anthropic_sonnet_model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(query, context, customer)}],
    )
    answer = resp.content[0].text.strip()

    # Per-agent NLI
    chunk_texts = [h["_source"]["text"] for h in hits]
    verified, warning = nli_checker.check(answer, chunk_texts)

    result: AgentResult = {
        "agent":    "product",
        "answer":   answer,
        "sources":  source_ids,
        "verified": verified,
        "warning":  warning,
    }
    return {"agent_results": [result]}
