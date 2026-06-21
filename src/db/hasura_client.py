import httpx
from src.config import get_settings

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

    resp = await get_client().post(
        s.hasura_url,
        json={"query": gql, "variables": variables or {}},
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise ValueError(f"GraphQL error: {data['errors']}")

    return data["data"]
