"""
Async Redis client — thin wrapper around redis.asyncio.
All cache reads/writes in the system go through this module.
"""
import json
import redis.asyncio as aioredis
from src.config import get_settings

_client: aioredis.Redis | None = None


async def init_client() -> None:
    global _client
    _client = aioredis.from_url(
        get_settings().redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


def get_client() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("Redis client not initialised — call init_client() at startup")
    return _client


async def get(key: str) -> dict | list | str | None:
    raw = await get_client().get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


async def set(key: str, value: dict | list | str, ttl: int) -> None:
    payload = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    await get_client().setex(key, ttl, payload)


async def delete(key: str) -> None:
    await get_client().delete(key)


# ── TTL constants (seconds) ────────────────────────────────────────────────────
TTL_SESSION   = 4 * 3600       # 4h  — assembled session context
TTL_CONTRACT  = 12 * 3600      # 12h — contract graph from Neo4j
TTL_RAG       = 6 * 3600       # 6h  — RAG retrieval results
TTL_QUERY_LONG  = 24 * 3600    # 24h — demographics, portfolio
TTL_QUERY_MED   = 6 * 3600     # 6h  — loan/deposit balances
TTL_QUERY_SHORT = 30 * 60      # 30m — transaction aggregations


# ── Key builders ──────────────────────────────────────────────────────────────
def key_session(session_id: str) -> str:
    return f"session:{session_id}"


def key_contract(customer_id: str) -> str:
    return f"contract:{customer_id}"


def key_rag(query_hash: str) -> str:
    return f"rag:{query_hash}"


def key_query(customer_id: str, query_type: str, params_hash: str) -> str:
    return f"query:{customer_id}:{query_type}:{params_hash}"
