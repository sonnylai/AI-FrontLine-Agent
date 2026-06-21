"""
RAG retrieval: BM25 (30%) + KNN semantic (70%) → RRF merge → Cohere rerank → top-5.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import cohere
from src.config import get_settings
from src.db.opensearch_client import bm25_search, knn_search

_co: cohere.Client | None = None
_executor = ThreadPoolExecutor(max_workers=4)


def _get_cohere() -> cohere.Client:
    global _co
    if _co is None:
        _co = cohere.Client(api_key=get_settings().cohere_api_key)
    return _co


def _embed_query(query: str) -> list[float]:
    resp = _get_cohere().embed(
        texts=[query],
        model=get_settings().cohere_embed_model,
        input_type="search_query",      # different from indexing input_type
    )
    return resp.embeddings[0]


def _rrf_merge(
    bm25_hits: list[dict],
    knn_hits:  list[dict],
    bm25_weight: float = 0.3,
    knn_weight:  float = 0.7,
    k: int = 60,
) -> list[dict]:
    """
    Reciprocal Rank Fusion.
    Returns deduplicated hits sorted by combined RRF score, highest first.
    """
    scores:   dict[str, float] = {}
    hit_map:  dict[str, dict]  = {}

    for rank, hit in enumerate(bm25_hits):
        doc_id = hit["_id"]
        scores[doc_id]  = scores.get(doc_id, 0.0) + bm25_weight / (k + rank + 1)
        hit_map[doc_id] = hit

    for rank, hit in enumerate(knn_hits):
        doc_id = hit["_id"]
        scores[doc_id]  = scores.get(doc_id, 0.0) + knn_weight / (k + rank + 1)
        hit_map[doc_id] = hit

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [hit_map[doc_id] for doc_id, _ in ranked]


def _cohere_rerank(query: str, hits: list[dict], top_n: int = 5) -> list[dict]:
    if not hits:
        return []
    documents = [h["_source"]["text"] for h in hits]
    results = _get_cohere().rerank(
        query=query,
        documents=documents,
        model="rerank-multilingual-v3.0",
        top_n=min(top_n, len(hits)),
    )
    return [hits[r.index] for r in results.results]


def retrieve(
    query: str,
    index: str = "product-docs",
    top_k_per_modality: int = 10,
    top_n_final: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """
    Synchronous retrieval — call from thread pool when inside async context.
    Returns top_n_final re-ranked chunks as OpenSearch hit dicts.
    """
    embedding = _embed_query(query)

    bm25_hits = bm25_search(index=index, query=query,   size=top_k_per_modality, filters=filters)
    knn_hits  = knn_search( index=index, vector=embedding, size=top_k_per_modality, filters=filters)

    merged = _rrf_merge(bm25_hits, knn_hits)
    return _cohere_rerank(query, merged, top_n=top_n_final)


async def aretrieve(
    query: str,
    index: str = "product-docs",
    top_k_per_modality: int = 10,
    top_n_final: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """Async wrapper — runs blocking OpenSearch + Cohere calls in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: retrieve(query, index, top_k_per_modality, top_n_final, filters),
    )


def format_chunks(hits: list[dict]) -> str:
    """Format retrieval results into a readable context block for the LLM prompt."""
    parts = []
    for i, hit in enumerate(hits, 1):
        src = hit["_source"]
        header = f"[Nguồn {i}] {src.get('product_name', '')} — {src.get('h3_section', src.get('h2_section', ''))}"
        parts.append(f"{header}\n{src['text']}")
    return "\n\n---\n\n".join(parts)
