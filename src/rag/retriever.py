"""
RAG retrieval: BM25 (30%) + KNN semantic (70%) → RRF merge → Cohere rerank → top-N
               + sibling-chunk expansion (fetch chunk_index+1 for same section).

LangSmith tracing strategy:
  - Blocking I/O (OpenSearch, Cohere) runs in a ThreadPoolExecutor.
  - @traceable log functions are called AFTER the thread returns, in the async event
    loop where LangChainTracer has set the active LangSmith run-tree context.
  - This guarantees each log span appears as a child of the LangGraph node in LangSmith,
    with zero duplicate API calls.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cohere
from langsmith import traceable
from src.config import get_settings
from src.db.opensearch_client import bm25_search, knn_search, get_client

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
        input_type="search_query",
    )
    return resp.embeddings[0]


def _chunk_summary(hit: dict) -> dict:
    s = hit["_source"]
    return {
        "id":      hit["_id"],
        "score":   round(hit.get("_score") or 0.0, 4),
        "tokens":  s.get("token_count", 0),
        "section": (s.get("h3_section") or s.get("h2_section") or "(intro)")[:80],
        "preview": s.get("text", "")[:150].replace("\n", " "),
    }


# ── @traceable spans — called from async context, appear as LangGraph children ──

@traceable(name="RAG·BM25", run_type="retriever")
def _log_bm25(query: str, hits: list[dict]) -> dict:
    return {"total": len(hits), "chunks": [_chunk_summary(h) for h in hits]}


@traceable(name="RAG·KNN", run_type="retriever")
def _log_knn(query: str, hits: list[dict]) -> dict:
    return {"total": len(hits), "chunks": [_chunk_summary(h) for h in hits]}


@traceable(name="RAG·RRF_Merge", run_type="chain")
def _log_rrf(bm25_count: int, knn_count: int, merged: list[dict]) -> dict:
    return {
        "bm25_count":    bm25_count,
        "knn_count":     knn_count,
        "merged_count":  len(merged),
        "top_15": [
            {"id": h["_id"], "section": _chunk_summary(h)["section"]}
            for h in merged[:15]
        ],
    }


@traceable(name="RAG·Cohere_Rerank", run_type="chain")
def _log_rerank(query: str, hits: list[dict], relevance_scores: list[float]) -> dict:
    return {
        "query":   query,
        "results": [
            {**_chunk_summary(h), "relevance": round(relevance_scores[i], 5)}
            for i, h in enumerate(hits)
        ],
    }


@traceable(name="RAG·Sibling_Expansion", run_type="chain")
def _log_siblings(before_ids: list[str], added_ids: list[str]) -> dict:
    return {
        "before": len(before_ids),
        "added":  added_ids,
        "after":  len(before_ids) + len(added_ids),
    }


# ── Intermediate result container ─────────────────────────────────────────────

@dataclass
class _RetrievalData:
    bm25_hits:       list[dict]
    knn_hits:        list[dict]
    merged:          list[dict]
    reranked:        list[dict]
    relevance_scores: list[float]
    final:           list[dict]
    added_ids:       list[str]


# ── Blocking retrieval (runs in thread, no tracing) ───────────────────────────

def _rrf_merge(bm25_hits: list[dict], knn_hits: list[dict], bw=0.3, kw=0.7, k=60) -> list[dict]:
    scores:  dict[str, float] = {}
    hit_map: dict[str, dict]  = {}
    for rank, h in enumerate(bm25_hits):
        scores[h["_id"]]  = scores.get(h["_id"], 0.0) + bw / (k + rank + 1)
        hit_map[h["_id"]] = h
    for rank, h in enumerate(knn_hits):
        scores[h["_id"]]  = scores.get(h["_id"], 0.0) + kw / (k + rank + 1)
        hit_map[h["_id"]] = h
    return [hit_map[did] for did, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def _cohere_rerank_raw(query: str, hits: list[dict], top_n: int) -> tuple[list[dict], list[float]]:
    if not hits:
        return [], []
    documents = [h["_source"]["text"] for h in hits]
    results   = _get_cohere().rerank(
        query=query, documents=documents,
        model="rerank-multilingual-v3.0", top_n=min(top_n, len(hits)),
    )
    return [hits[r.index] for r in results.results], [r.relevance_score for r in results.results]


def _fetch_siblings_raw(hits: list[dict], index: str) -> tuple[list[dict], list[str]]:
    present  = {h["_id"] for h in hits}
    extra:   list[dict] = []
    added:   list[str]  = []
    for h in hits:
        s      = h["_source"]
        nxt_id = f"{s['doc_id']}__{s['chunk_index'] + 1}"
        if nxt_id in present:
            continue
        try:
            resp = get_client().get(index=index, id=nxt_id)
        except Exception:
            continue
        nxt     = resp["_source"]
        same_h3 = s.get("h3_section") and nxt.get("h3_section") == s["h3_section"]
        same_h2 = (not s.get("h3_section")) and nxt.get("h2_section") == s["h2_section"]
        if same_h3 or same_h2:
            extra.append({"_id": nxt_id, "_score": 0.0, "_source": nxt})
            present.add(nxt_id)
            added.append(nxt_id)
    return hits + extra, added


def _retrieve_blocking(
    query: str,
    index: str,
    top_k: int,
    top_n: int,
    filters: dict | None,
) -> _RetrievalData:
    """All blocking I/O in one function — called from thread pool, no tracing."""
    embedding = _embed_query(query)
    bm25_hits = bm25_search(index=index, query=query,     size=top_k, filters=filters)
    knn_hits  = knn_search( index=index, vector=embedding, size=top_k, filters=filters)
    merged    = _rrf_merge(bm25_hits, knn_hits)
    reranked, scores = _cohere_rerank_raw(query, merged, top_n)
    final, added_ids = _fetch_siblings_raw(reranked, index)
    return _RetrievalData(bm25_hits, knn_hits, merged, reranked, scores, final, added_ids)


# ── Public entry points ────────────────────────────────────────────────────────

def retrieve(
    query: str,
    index: str = "product-docs",
    top_k_per_modality: int = 10,
    top_n_final: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """Synchronous entry point (for scripts / rag_trace.py). No LangSmith spans."""
    d = _retrieve_blocking(query, index, top_k_per_modality, top_n_final, filters)
    return d.final


async def aretrieve(
    query: str,
    index: str = "product-docs",
    top_k_per_modality: int = 10,
    top_n_final: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """
    Async entry point used by all agents.
    1. Runs all blocking I/O in a thread (no tracing there).
    2. Calls @traceable log functions in the async event loop — this is where the
       LangChainTracer has set the active LangSmith run-tree context, so each log
       function appears as a child span inside the LangGraph node's trace.
    """
    loop = asyncio.get_event_loop()
    d = await loop.run_in_executor(
        _executor,
        lambda: _retrieve_blocking(query, index, top_k_per_modality, top_n_final, filters),
    )

    # Log spans in async context → guaranteed child spans in LangSmith
    _log_bm25(query, d.bm25_hits)
    _log_knn(query, d.knn_hits)
    _log_rrf(len(d.bm25_hits), len(d.knn_hits), d.merged)
    _log_rerank(query, d.reranked, d.relevance_scores)
    _log_siblings([h["_id"] for h in d.reranked], d.added_ids)

    return d.final


def format_chunks(hits: list[dict]) -> str:
    parts = []
    for i, hit in enumerate(hits, 1):
        src    = hit["_source"]
        header = f"[Nguồn {i}] {src.get('product_name', '')} — {src.get('h3_section', src.get('h2_section', ''))}"
        parts.append(f"{header}\n{src['text']}")
    return "\n\n---\n\n".join(parts)
