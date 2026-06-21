"""
RAG pipeline trace — run from project root:
  python scripts/rag_trace.py "your query here"

Prints every stage: BM25 hits, KNN hits, RRF scores, Cohere relevance, final chunks.
Use this to diagnose why a specific question returns wrong/incomplete chunks.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Init OpenSearch before importing retriever modules
from src.db.opensearch_client import init_client, bm25_search, knn_search
init_client()

import cohere
from src.config import get_settings

s   = get_settings()
co  = cohere.Client(api_key=s.cohere_api_key)

INDEX = "product-docs"
TOP_K = 20
TOP_N = 5


def rrf(bm25_hits, knn_hits, bw=0.3, kw=0.7, k=60):
    scores, hit_map = {}, {}
    for rank, h in enumerate(bm25_hits):
        scores[h["_id"]] = scores.get(h["_id"], 0) + bw / (k + rank + 1)
        hit_map[h["_id"]] = h
    for rank, h in enumerate(knn_hits):
        scores[h["_id"]] = scores.get(h["_id"], 0) + kw / (k + rank + 1)
        hit_map[h["_id"]] = h
    return [(hit_map[d], sc) for d, sc in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def label(h):
    s = h["_source"]
    return (s.get("h3_section") or s.get("h2_section") or "(intro)")[:60]


def trace(query: str, top_k: int = TOP_K, top_n: int = TOP_N):
    SEP = "─" * 72
    print(f"\nQUERY: {query!r}")
    print(f"top_k_per_modality={top_k}  top_n_final={top_n}\n")

    # ── Stage 1: BM25 ────────────────────────────────────────────────────────
    bm25 = bm25_search(index=INDEX, query=query, size=top_k)
    print(f"{SEP}\n[Stage 1] BM25 — top {top_k}\n{SEP}")
    for i, h in enumerate(bm25, 1):
        src = h["_source"]
        print(f"  #{i:02d}  score={h['_score']:7.3f}  tok={src['token_count']:>3}  {h['_id']}")
        print(f"         {label(h)}")

    # ── Stage 2: KNN semantic ─────────────────────────────────────────────────
    emb = co.embed(texts=[query], model=s.cohere_embed_model, input_type="search_query").embeddings[0]
    knn = knn_search(index=INDEX, vector=emb, size=top_k)
    print(f"\n{SEP}\n[Stage 2] KNN semantic — top {top_k}\n{SEP}")
    for i, h in enumerate(knn, 1):
        src = h["_source"]
        print(f"  #{i:02d}  score={h['_score']:7.4f}  tok={src['token_count']:>3}  {h['_id']}")
        print(f"         {label(h)}")

    # ── Stage 3: RRF merge ────────────────────────────────────────────────────
    merged_scored = rrf(bm25, knn)
    print(f"\n{SEP}\n[Stage 3] RRF merged — top {min(20, len(merged_scored))}\n{SEP}")
    for i, (h, sc) in enumerate(merged_scored[:20], 1):
        src = h["_source"]
        print(f"  #{i:02d}  rrf={sc:.5f}  tok={src['token_count']:>3}  {h['_id']}")
        print(f"         {label(h)}")

    # ── Stage 4: Cohere rerank ────────────────────────────────────────────────
    merged = [h for h, _ in merged_scored]
    docs   = [h["_source"]["text"] for h in merged]
    rr     = co.rerank(query=query, documents=docs, model="rerank-multilingual-v3.0", top_n=top_n)
    reranked = [merged[r.index] for r in rr.results]

    print(f"\n{SEP}\n[Stage 4] Cohere rerank → top {top_n}\n{SEP}")
    for r in rr.results:
        h   = merged[r.index]
        src = h["_source"]
        print(f"  rel={r.relevance_score:.5f}  tok={src['token_count']:>3}  {h['_id']}")
        print(f"  section: {label(h)}")
        print(f"  text:    {src['text'][:120].replace(chr(10), ' ')}")
        print()

    # ── Stage 5: Sibling expansion ────────────────────────────────────────────
    from src.db.opensearch_client import get_client
    present = {h["_id"] for h in reranked}
    siblings_added = []
    for h in reranked:
        src    = h["_source"]
        nxt_id = f"{src['doc_id']}__{src['chunk_index'] + 1}"
        if nxt_id in present:
            continue
        try:
            resp = get_client().get(index=INDEX, id=nxt_id)
        except Exception:
            continue
        nxt     = resp["_source"]
        same_h3 = src.get("h3_section") and nxt.get("h3_section") == src["h3_section"]
        same_h2 = (not src.get("h3_section")) and nxt.get("h2_section") == src["h2_section"]
        if same_h3 or same_h2:
            siblings_added.append(nxt_id)
            present.add(nxt_id)
            reranked.append({"_id": nxt_id, "_score": 0.0, "_source": nxt})

    print(f"{SEP}\n[Stage 5] Sibling chunk expansion\n{SEP}")
    if siblings_added:
        print(f"  Added {len(siblings_added)} sibling chunk(s): {siblings_added}")
    else:
        print(f"  No siblings added.")

    # ── Final answer context ──────────────────────────────────────────────────
    print(f"\n{SEP}\n[FINAL] Chunks sent to LLM ({len(reranked)} total)\n{SEP}")
    for i, h in enumerate(reranked, 1):
        src = h["_source"]
        print(f"\n--- Chunk {i} ({h['_id']}, {src['token_count']} tok) ---")
        print(f"Section: {label(h)}")
        print(src["text"][:400])
        if len(src["text"]) > 400:
            print(f"  ... [{src['token_count']} tokens total]")


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "các quỹ liên kết của sản phẩm Banca"
    trace(query)
