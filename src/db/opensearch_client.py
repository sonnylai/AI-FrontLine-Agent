from opensearchpy import OpenSearch
from src.config import get_settings

_client: OpenSearch | None = None


def init_client():
    global _client
    s = get_settings()
    _client = OpenSearch(
        hosts=[s.opensearch_url],
        http_auth=(s.opensearch_user, s.opensearch_password),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    )


def get_client() -> OpenSearch:
    if _client is None:
        raise RuntimeError("OpenSearch client not initialised")
    return _client


def bm25_search(index: str, query: str, size: int = 10, filters: dict | None = None) -> list[dict]:
    must = [{"match": {"text": {"query": query, "operator": "or"}}}]
    if filters:
        must.append({"term": filters})

    body = {"query": {"bool": {"must": must}}, "size": size}
    resp = get_client().search(index=index, body=body)
    return resp["hits"]["hits"]


def knn_search(index: str, vector: list[float], size: int = 10, filters: dict | None = None) -> list[dict]:
    knn_clause: dict = {"vector": vector, "k": size}
    if filters:
        knn_clause["filter"] = {"term": filters}

    body = {"query": {"knn": {"embedding": knn_clause}}, "size": size}
    resp = get_client().search(index=index, body=body)
    return resp["hits"]["hits"]
