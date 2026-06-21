import json
import logging
import re
import httpx
from src.config import get_settings

logger = logging.getLogger("afl.hasura")

_client: httpx.AsyncClient | None = None


def init_client():
    global _client
    _client = httpx.AsyncClient(timeout=30)


async def close_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("Hasura client not initialised")
    return _client


async def query(gql: str, variables: dict | None = None, rep_jwt: str | None = None) -> dict:
    """
    Execute a GraphQL query against Hasura.
    Uses admin secret by default; pass rep_jwt to run as a sales_rep
    (row-level permissions apply automatically).
    """
    s = get_settings()
    headers = {"Content-Type": "application/json"}

    if rep_jwt:
        headers["Authorization"] = f"Bearer {rep_jwt}"
    else:
        headers["X-Hasura-Admin-Secret"] = s.hasura_admin_secret

    payload = {"query": gql, "variables": variables or {}}

    # Extract query name from first line for compact logging
    op_name = (re.search(r"query\s+(\w+)", gql) or re.search(r"mutation\s+(\w+)", gql))
    op_label = op_name.group(1) if op_name else "GraphQL"
    logger.info(
        "Hasura ▶ %s  vars=%s",
        op_label,
        json.dumps(variables or {}, ensure_ascii=False, default=str),
    )

    resp = await get_client().post(s.hasura_url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        logger.error("Hasura ✗ %s  errors=%s", op_label, data["errors"])
        raise ValueError(f"GraphQL error: {data['errors']}")

    # Log top-level keys and row counts for quick inspection
    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in data["data"].items()}
    logger.info("Hasura ◀ %s  result=%s", op_label, summary)

    return data["data"]
