"""
ProductKnowledgeAgent: RAG retrieval → Sonnet reasoning → per-agent NLI.
RAG results are cached in Redis (rag:{query_hash}, TTL 6h).
"""
import hashlib
import anthropic
from src.agents.state import AgentState, AgentResult
from src.cache import redis_client
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
    products = customer.get("products_held", [])
    held     = ", ".join(p if isinstance(p, str) else p.get("product_code", "") for p in products)
    return f"""THÔNG TIN KHÁCH HÀNG:
- Phân khúc: {segment}
- Sản phẩm đang sử dụng: {held}

TÀI LIỆU SẢN PHẨM:
{context}

CÂU HỎI: {query}

Hãy trả lời dựa trên tài liệu trên."""


async def _get_rag_hits(query: str, index: str) -> list[dict]:
    """Cache-aside: check Redis first, fall back to OpenSearch."""
    cache_key = redis_client.key_rag(
        hashlib.md5(f"{index}:{query}".encode()).hexdigest()
    )
    cached = await redis_client.get(cache_key)
    if cached:
        return cached

    hits = await retriever.aretrieve(query=query, index=index, top_n_final=5)

    # Store only serializable fields
    serializable = [
        {"_id": h["_id"], "_source": {"text": h["_source"]["text"],
         "product_name": h["_source"].get("product_name", ""),
         "h2_section":   h["_source"].get("h2_section", ""),
         "h3_section":   h["_source"].get("h3_section", "")}}
        for h in hits
    ]
    await redis_client.set(cache_key, serializable, ttl=redis_client.TTL_RAG)
    return hits   # return original hits (with all fields) for this call


async def run(state: AgentState) -> dict:
    query    = state.get("rewritten_query") or state["message"]
    customer = state.get("customer_360", {})

    hits       = await _get_rag_hits(query, "product-docs")
    context    = retriever.format_chunks(hits)
    source_ids = [h["_id"] for h in hits]

    resp = await _get_client().messages.create(
        model=get_settings().anthropic_sonnet_model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(query, context, customer)}],
    )
    answer = resp.content[0].text.strip()

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
