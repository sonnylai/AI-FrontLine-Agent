"""
Session context store — Orchestrator node ①.

On session START:
  1. Check Redis for assembled context (cache hit → inject directly)
  2. On miss: load customer_360 from Hasura + last 5 summaries from OpenSearch
  3. Assemble into one context dict → cache in Redis TTL=4h

On session END:
  1. Haiku summarizes conversation from messages state
  2. Write summary to OpenSearch (vector store)
  3. Delete Redis session key
"""
import hashlib
import json
import anthropic
from opensearchpy import OpenSearch

from src.cache import redis_client
from src.config import get_settings
from src.db import hasura_client, opensearch_client

_haiku: anthropic.AsyncAnthropic | None = None


def _get_haiku() -> anthropic.AsyncAnthropic:
    global _haiku
    if _haiku is None:
        _haiku = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _haiku


# ── GraphQL query — customer 360 + long-term memory ──────────────────────────

_CUSTOMER_QUERY = """
query LoadSession($id: String!) {
  customers(where: {customer_id: {_eq: $id}}) {
    customer_id full_name segment kyc_status
    credit_score loyalty_points city occupation income_range relationship_since
    assigned_rep_id
    rep { rep_id full_name branch }
    products_held { product_code }
    contracts(order_by: {start_date: desc}) {
      contract_id product_type product_name status
      start_date end_date key_amount extra_fields
      clauses {
        clause_id clause_number title benefit
        customer_qualifies disqualification_reason
      }
      coverages { coverage_id coverage_type limit_amount conditions }
    }
    transactions(limit: 30, order_by: {transaction_date: desc}) {
      transaction_id transaction_date amount type
      merchant_name merchant_category description status
    }
  }
}
"""


# ── Long-term summaries from OpenSearch ───────────────────────────────────────

def _load_summaries(customer_id: str, top_n: int = 5) -> list[dict]:
    """Load last N conversation summaries from OpenSearch sorted by date."""
    client: OpenSearch = opensearch_client.get_client()
    try:
        resp = client.search(
            index="conversation-summaries",
            body={
                "query": {"term": {"customer_id": customer_id}},
                "sort": [{"session_date": {"order": "desc"}}],
                "size": top_n,
            },
        )
        return [h["_source"] for h in resp["hits"]["hits"]]
    except Exception:
        return []


def _write_summary(customer_id: str, session_id: str, summary: dict) -> None:
    """Write a Haiku-generated summary to OpenSearch."""
    client: OpenSearch = opensearch_client.get_client()
    doc_id = hashlib.md5(f"{session_id}".encode()).hexdigest()
    try:
        client.index(
            index="conversation-summaries",
            id=doc_id,
            body={**summary, "customer_id": customer_id, "session_id": session_id},
        )
    except Exception:
        pass


# ── Assemble session context ──────────────────────────────────────────────────

async def _assemble(customer_id: str) -> dict:
    """Load all sources and return assembled context dict."""
    data = await hasura_client.query(_CUSTOMER_QUERY, {"id": customer_id})
    rows = data.get("customers", [])
    customer_360 = rows[0] if rows else {}

    summaries = _load_summaries(customer_id)

    return {
        "customer_360": customer_360,
        "long_term_summaries": summaries,
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def load(session_id: str, customer_id: str) -> dict:
    """
    Load session context.
    Returns assembled dict with customer_360 + long_term_summaries.
    Caches in Redis on miss.
    """
    key = redis_client.key_session(session_id)
    cached = await redis_client.get(key)
    if cached:
        return cached

    context = await _assemble(customer_id)
    await redis_client.set(key, context, ttl=redis_client.TTL_SESSION)
    return context


async def end(session_id: str, customer_id: str, messages: list[dict]) -> None:
    """
    Called on POST /api/sessions/end.
    Haiku summarizes → writes to OpenSearch → clears Redis.
    """
    if not messages:
        await redis_client.delete(redis_client.key_session(session_id))
        return

    conversation_text = "\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in messages
    )

    try:
        resp = await _get_haiku().messages.create(
            model=get_settings().anthropic_haiku_model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": f"""Tóm tắt cuộc hội thoại tư vấn ngân hàng sau thành JSON:

{conversation_text}

Trả về JSON:
{{
  "session_date": "YYYY-MM-DD",
  "summary": "tóm tắt ngắn gọn",
  "key_concerns": ["mối quan tâm 1", ...],
  "products_discussed": ["sản phẩm 1", ...],
  "sentiment": "positive|neutral|hesitant|negative"
}}""",
            }],
        )
        raw = resp.content[0].text.strip().strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
        summary = json.loads(raw)
    except Exception:
        from datetime import date
        summary = {
            "session_date": date.today().isoformat(),
            "summary": "Phiên tư vấn không thể tóm tắt tự động.",
            "key_concerns": [],
            "products_discussed": [],
            "sentiment": "neutral",
        }

    _write_summary(customer_id, session_id, summary)
    await redis_client.delete(redis_client.key_session(session_id))
