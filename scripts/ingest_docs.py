"""
Phase 1E — RAG ingestion: chunk product docs → embed via Cohere → index into OpenSearch.
Strategy: Stage 1 MarkdownHeaderTextSplitter (H2+H3), Stage 2 RecursiveCharacterTextSplitter
          if chunk > 400 tokens. Preserves tables and FAQ pairs.
Run: python scripts/ingest_docs.py
"""
import os
import re
import sys
import json
import time
from pathlib import Path

import tiktoken
import cohere
from opensearchpy import OpenSearch, helpers
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Clients ──────────────────────────────────────────────────────────────────
co = cohere.Client(api_key=os.getenv("COHERE_API_KEY"))

os_client = OpenSearch(
    hosts=[os.getenv("OPENSEARCH_URL", "https://localhost:9200")],
    http_auth=(
        os.getenv("OPENSEARCH_USER", "admin"),
        os.getenv("OPENSEARCH_PASSWORD"),
    ),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
)

# ── Config ───────────────────────────────────────────────────────────────────
DOCS_DIR     = Path(__file__).parent.parent / "data" / "documents"
INDEX_NAME   = "product-docs"
CHUNK_TOKENS = 400
OVERLAP_TOKENS = 80
EMBED_BATCH  = 48   # Cohere max batch = 96; keep conservative

enc = tiktoken.get_encoding("cl100k_base")

# Map directory name → product_category label
CATEGORY_MAP = {
    "banca":                  "banca",
    "certificate_of_deposit": "certificate_of_deposit",
    "credit_card":            "credit_card",
    "debit_card":             "debit_card",
    "lending":                "lending",
    "loan":                   "loan",
    "non_life_insurance":     "non_life_insurance",
    "term_deposit":           "term_deposit",
    "vip_program":            "vip_program",
    "life_insurance":         "life_insurance",
}


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def extract_product_name(text: str, filename: str) -> str:
    """Pull H1 title from the document, fall back to filename."""
    match = re.search(r"^# (.+)$", text, re.MULTILINE)
    if match:
        # Strip markdown bold and trailing dashes
        name = re.sub(r"\*\*|—.*$", "", match.group(1)).strip()
        return name
    return filename.replace("tcb_", "TCB ").replace("_", " ").title()


def protect_tables(text: str) -> str:
    """Replace table row newlines with a sentinel so splitter doesn't cut mid-table."""
    lines = text.split("\n")
    result, in_table = [], False
    for line in lines:
        if line.startswith("|"):
            in_table = True
            result.append(line)
        else:
            if in_table and line.strip() == "":
                result.append("⟦TABLE_END⟧")
            in_table = False
            result.append(line)
    return "\n".join(result)


def restore_tables(text: str) -> str:
    return text.replace("⟦TABLE_END⟧", "")


# ── Two-stage chunker (no langchain dependency) ──────────────────────────────

def split_by_headers(text: str) -> list[dict]:
    """
    Stage 1: split markdown text on ## and ### headings.
    Returns list of {"text": ..., "h2": ..., "h3": ...}
    """
    sections = []
    current_h2 = current_h3 = ""
    current_lines: list[str] = []

    def flush():
        body = "\n".join(current_lines).strip()
        if body:
            sections.append({"text": body, "h2": current_h2, "h3": current_h3})

    for line in text.split("\n"):
        if line.startswith("### "):
            flush()
            current_lines = [line]
            current_h3 = line.lstrip("# ").strip()
        elif line.startswith("## "):
            flush()
            current_lines = [line]
            current_h2 = line.lstrip("# ").strip()
            current_h3 = ""
        else:
            current_lines.append(line)

    flush()
    return sections


def recursive_split(text: str, max_tokens: int, overlap: int) -> list[str]:
    """
    Stage 2: recursively split text that exceeds max_tokens.
    Tries paragraph breaks first, then line breaks, then sentences, then words.
    """
    if count_tokens(text) <= max_tokens:
        return [text]

    separators = ["\n\n", "\n", ". ", " "]
    for sep in separators:
        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        chunks, current, current_tokens = [], [], 0
        for part in parts:
            part_tokens = count_tokens(part + sep)
            if current_tokens + part_tokens > max_tokens and current:
                chunk_text = sep.join(current).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                # Carry overlap: keep last N tokens worth of parts
                overlap_parts, overlap_tokens = [], 0
                for p in reversed(current):
                    t = count_tokens(p + sep)
                    if overlap_tokens + t > overlap:
                        break
                    overlap_parts.insert(0, p)
                    overlap_tokens += t
                current = overlap_parts + [part]
                current_tokens = sum(count_tokens(p + sep) for p in current)
            else:
                current.append(part)
                current_tokens += part_tokens

        if current:
            chunk_text = sep.join(current).strip()
            if chunk_text:
                chunks.append(chunk_text)

        # Only use this separator level if it actually split the text
        if len(chunks) > 1:
            return chunks

    # Last resort: hard cut
    tokens = enc.encode(text)
    result = []
    for i in range(0, len(tokens), max_tokens - overlap):
        result.append(enc.decode(tokens[i: i + max_tokens]))
    return result


def chunk_document(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    protected = protect_tables(raw)

    product_name = extract_product_name(raw, path.stem)
    category     = CATEGORY_MAP.get(path.parent.name, path.parent.name)
    doc_id       = path.stem

    sections = split_by_headers(protected)

    chunks, chunk_index = [], 0
    for section in sections:
        text = restore_tables(section["text"]).strip()
        if not text:
            continue

        h2, h3 = section["h2"], section["h3"]

        if count_tokens(text) <= CHUNK_TOKENS:
            chunks.append({
                "doc_id":           doc_id,
                "product_category": category,
                "product_name":     product_name,
                "h2_section":       h2,
                "h3_section":       h3,
                "chunk_index":      chunk_index,
                "token_count":      count_tokens(text),
                "source_file":      str(path.relative_to(DOCS_DIR.parent.parent)),
                "text":             text,
            })
            chunk_index += 1
        else:
            for sub in recursive_split(text, CHUNK_TOKENS, OVERLAP_TOKENS):
                sub = sub.strip()
                if not sub:
                    continue
                chunks.append({
                    "doc_id":           doc_id,
                    "product_category": category,
                    "product_name":     product_name,
                    "h2_section":       h2,
                    "h3_section":       h3,
                    "chunk_index":      chunk_index,
                    "token_count":      count_tokens(sub),
                    "source_file":      str(path.relative_to(DOCS_DIR.parent.parent)),
                    "text":             sub,
                })
                chunk_index += 1

    return chunks


# ── Embedding + indexing ─────────────────────────────────────────────────────
def embed_batch(texts: list[str]) -> list[list[float]]:
    resp = co.embed(
        texts=texts,
        model=os.getenv("COHERE_EMBED_MODEL", "embed-multilingual-v3.0"),
        input_type="search_document",
    )
    return resp.embeddings


def bulk_index(chunks: list[dict]):
    actions = [
        {
            "_index": INDEX_NAME,
            "_id":    f"{c['doc_id']}__{c['chunk_index']}",
            "_source": c,
        }
        for c in chunks
    ]
    success, errors = helpers.bulk(os_client, actions, raise_on_error=False)
    return success, errors


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    doc_files = sorted(DOCS_DIR.rglob("*.md"))
    print(f"Found {len(doc_files)} documents in {DOCS_DIR}")

    all_chunks: list[dict] = []
    for path in doc_files:
        chunks = chunk_document(path)
        all_chunks.extend(chunks)
        print(f"  {path.name:<55} {len(chunks):>3} chunks")

    print(f"\nTotal chunks: {len(all_chunks)}")
    print(f"Embedding in batches of {EMBED_BATCH} (Cohere)...")

    indexed = 0
    for i in range(0, len(all_chunks), EMBED_BATCH):
        batch = all_chunks[i : i + EMBED_BATCH]
        texts = [c["text"] for c in batch]

        embeddings = embed_batch(texts)
        for chunk, emb in zip(batch, embeddings):
            chunk["embedding"] = emb

        success, errors = bulk_index(batch)
        indexed += success
        if errors:
            print(f"  Batch {i//EMBED_BATCH + 1} errors: {errors[:2]}")

        print(f"  Batch {i//EMBED_BATCH + 1}/{-(-len(all_chunks)//EMBED_BATCH)}"
              f" — {indexed} chunks indexed", end="\r")

        # Cohere free tier: 100 calls/min
        if i + EMBED_BATCH < len(all_chunks):
            time.sleep(0.6)

    print(f"\n\nIndexed {indexed}/{len(all_chunks)} chunks into '{INDEX_NAME}' ✅")

    # Verify
    os_client.indices.refresh(index=INDEX_NAME)
    count = os_client.count(index=INDEX_NAME)["count"]
    print(f"OpenSearch doc count: {count}")


if __name__ == "__main__":
    main()
