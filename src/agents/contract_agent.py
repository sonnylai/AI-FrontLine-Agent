"""
ContractKnowledgeAgent: Neo4j traversal + RAG → Sonnet reasoning → per-agent NLI.
Contract graph data cached in Redis (contract:{customer_id}, TTL 12h).
RAG results cached in Redis (rag:{query_hash}, TTL 6h).
"""
import hashlib
import json
import anthropic
from src.agents.state import AgentState, AgentResult
from src.cache import redis_client
from src.config import get_settings
from src.db import neo4j_client
from src.rag import retriever
from src.safety import nli_checker

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


_SYSTEM = """Bạn là chuyên gia hợp đồng tài chính của Techcombank.
Nhiệm vụ: trả lời câu hỏi về hợp đồng cụ thể của khách hàng.

Quy tắc:
- Dựa vào dữ liệu hợp đồng thực tế của khách hàng.
- Khi nói về điều khoản, trích dẫn số điều khoản cụ thể (ví dụ: Điều Khoản 7.3).
- Nếu khách hàng ĐỦ điều kiện, giải thích rõ tại sao. Nếu KHÔNG ĐỦ, giải thích lý do.
- Trả lời bằng tiếng Việt, chính xác và chuyên nghiệp."""


async def _get_contract_records(customer_id: str) -> list[dict]:
    """Cache-aside: Redis → Neo4j."""
    cache_key = redis_client.key_contract(customer_id)
    cached = await redis_client.get(cache_key)
    if cached:
        return cached

    records = await neo4j_client.run_query("""
        MATCH (cu:Customer {customer_id: $cid})-[:HAS_CONTRACT]->(ct:Contract)
        OPTIONAL MATCH (ct)-[:HAS_CLAUSE]->(cl:Clause)
        OPTIONAL MATCH (ct)-[:HAS_COVERAGE]->(cov:Coverage)
        RETURN ct.contract_id   AS contract_id,
               ct.product_name  AS product_name,
               ct.product_type  AS product_type,
               ct.status        AS status,
               ct.start_date    AS start_date,
               ct.end_date      AS end_date,
               ct.key_amount    AS key_amount,
               ct.extra_fields  AS extra_fields,
               collect(DISTINCT {
                   clause_number: cl.clause_number,
                   title:         cl.title,
                   benefit:       cl.benefit,
                   conditions:    cl.conditions,
                   qualifies:     cl.customer_qualifies,
                   disqualification: cl.disqualification_reason
               }) AS clauses,
               collect(DISTINCT {
                   type:  cov.coverage_type,
                   limit: cov.limit_amount,
                   conditions: cov.conditions
               }) AS coverages
    """, {"cid": customer_id})

    await redis_client.set(cache_key, records, ttl=redis_client.TTL_CONTRACT)
    return records


async def _get_rag_hits(query: str, index: str) -> list[dict]:
    """Cache-aside for RAG results."""
    cache_key = redis_client.key_rag(
        hashlib.md5(f"{index}:{query}".encode()).hexdigest()
    )
    cached = await redis_client.get(cache_key)
    if cached:
        return cached

    hits = await retriever.aretrieve(query=query, index=index, top_n_final=3)
    serializable = [
        {"_id": h["_id"], "_source": {"text": h["_source"]["text"],
         "product_name": h["_source"].get("product_name", ""),
         "h2_section":   h["_source"].get("h2_section", ""),
         "h3_section":   h["_source"].get("h3_section", "")}}
        for h in hits
    ]
    await redis_client.set(cache_key, serializable, ttl=redis_client.TTL_RAG)
    return hits


def _format_contracts(records: list[dict]) -> str:
    lines = []
    for r in records:
        extra = {}
        if r.get("extra_fields"):
            try:
                extra = json.loads(r["extra_fields"])
            except Exception:
                pass

        lines.append(f"\n## {r['product_name']} ({r['contract_id']})")
        lines.append(f"Trạng thái: {r['status']} | Từ: {r.get('start_date','N/A')} đến {r.get('end_date','N/A')}")
        if r.get("key_amount"):
            lines.append(f"Số tiền chính: {r['key_amount']:,} VND")
        for k, v in extra.items():
            lines.append(f"{k}: {v}")

        clauses = [c for c in (r.get("clauses") or []) if c.get("clause_number")]
        if clauses:
            lines.append("\nĐiều khoản:")
            for cl in clauses:
                q = ("✅ ĐỦ ĐIỀU KIỆN" if cl.get("qualifies") else
                     "❌ KHÔNG ĐỦ: " + (cl.get("disqualification") or "")
                     if cl.get("qualifies") is False else "⬜ Chưa đánh giá")
                lines.append(f"  [{cl['clause_number']}] {cl.get('title','')} — {q}")
                if cl.get("benefit"):
                    lines.append(f"      Quyền lợi: {cl['benefit']}")

        coverages = [c for c in (r.get("coverages") or []) if c.get("type")]
        if coverages:
            lines.append("\nPhạm vi bảo hiểm:")
            for cov in coverages:
                limit = f"{cov['limit']:,} VND" if cov.get("limit") else "N/A"
                lines.append(f"  {cov['type']}: tối đa {limit}")

    return "\n".join(lines)


async def run(state: AgentState) -> dict:
    query       = state.get("rewritten_query") or state["message"]
    customer_id = state["customer_id"]

    # Neo4j (cached)
    records          = await _get_contract_records(customer_id)
    contract_context = _format_contracts(records) if records else "Không tìm thấy hợp đồng."

    # RAG on clause text (cached)
    rag_hits    = await _get_rag_hits(query, "contract-clauses")
    rag_context = retriever.format_chunks(rag_hits) if rag_hits else ""

    prompt = f"""DỮ LIỆU HỢP ĐỒNG CỦA KHÁCH HÀNG {customer_id}:
{contract_context}

{"TÀI LIỆU ĐIỀU KHOẢN BỔ SUNG:" + chr(10) + rag_context if rag_context else ""}

CÂU HỎI: {query}

Hãy trả lời dựa trên hợp đồng thực tế của khách hàng."""

    resp = await _get_client().messages.create(
        model=get_settings().anthropic_sonnet_model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = resp.content[0].text.strip()

    chunk_texts = [contract_context] + [h["_source"]["text"] for h in rag_hits]
    verified, warning = nli_checker.check(answer, chunk_texts, agent="contract")

    result: AgentResult = {
        "agent":    "contract",
        "answer":   answer,
        "sources":  [r["contract_id"] for r in records],
        "verified": verified,
        "warning":  warning,
    }
    return {"agent_results": [result]}
