"""
Phase 1D — Create OpenSearch indexes: product-docs and contract-clauses.
Run: python scripts/create_indexes.py
"""
import os
import sys
from pathlib import Path

from opensearchpy import OpenSearch
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

client = OpenSearch(
    hosts=[os.getenv("OPENSEARCH_URL", "https://localhost:9200")],
    http_auth=(
        os.getenv("OPENSEARCH_USER", "admin"),
        os.getenv("OPENSEARCH_PASSWORD", "Frontline2026@Xyz"),
    ),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
)

# Shared field mappings used by both indexes
COMMON_PROPERTIES = {
    "text": {
        "type": "text",
        "analyzer": "standard",
        "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}
    },
    "embedding": {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {
            "name":       "hnsw",
            "engine":     "nmslib",
            "space_type": "cosinesimil",
            "parameters": {"m": 16, "ef_construction": 256},
        },
    },
    "chunk_index": {"type": "integer"},
    "token_count": {"type": "integer"},
    "source_file": {"type": "keyword"},
}

INDEXES = {
    "product-docs": {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            }
        },
        "mappings": {
            "properties": {
                **COMMON_PROPERTIES,
                "doc_id":           {"type": "keyword"},
                "product_category": {"type": "keyword"},
                "product_name":     {"type": "keyword"},
                "h2_section":       {"type": "keyword"},
                "h3_section":       {"type": "keyword"},
            }
        },
    },
    "contract-clauses": {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            }
        },
        "mappings": {
            "properties": {
                **COMMON_PROPERTIES,
                "clause_id":      {"type": "keyword"},
                "contract_id":    {"type": "keyword"},
                "customer_id":    {"type": "keyword"},
                "product_type":   {"type": "keyword"},
                "clause_number":  {"type": "keyword"},
                "clause_title":   {"type": "text"},
            }
        },
    },
}


def main():
    print("Checking OpenSearch connection...")
    info = client.info()
    print(f"  Connected: OpenSearch {info['version']['number']}")

    for index_name, body in INDEXES.items():
        if client.indices.exists(index=index_name):
            print(f"  Deleting existing index '{index_name}'...")
            client.indices.delete(index=index_name)

        print(f"  Creating index '{index_name}'...")
        client.indices.create(index=index_name, body=body)
        print(f"  '{index_name}' created ✅")

    print("\nVerifying indexes:")
    for index_name in INDEXES:
        stats = client.indices.stats(index=index_name)
        doc_count = stats["indices"][index_name]["total"]["docs"]["count"]
        print(f"  {index_name}: {doc_count} docs (empty, ready for ingestion)")

    print("\nOpenSearch indexes ready.")


if __name__ == "__main__":
    main()
