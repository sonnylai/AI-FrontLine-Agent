# AI FrontLine Agent V2

A multi-agent AI assistant for Techcombank sales representatives. The agent answers natural-language questions about customers by combining structured Postgres data, graph (Neo4j) contract data, and RAG product knowledge — streamed in real time via SSE.

---

## Architecture overview

```
Browser (Sales Rep UI)
    │  SSE stream
    ▼
FastAPI  ──JWT──▶  LangGraph Orchestrator
                        │
          ┌─────────────┼──────────────┬──────────────┐
          ▼             ▼              ▼               ▼
   QueryDispatcher  ProductAgent  ContractAgent  AdvisoryAgent
   (Hasura/Postgres) (OpenSearch   (Neo4j +       (NBA rules +
                      RAG + NLI)    RAG + NLI)     RAG + NLI)
          └─────────────┴──────────────┴───────────────┘
                        │ Aggregator (Sonnet streaming)
                        │ OutputGuardrail + FinalNLI
                        ▼
                   SSE token stream
```

**LLMs:** Claude Sonnet 4.6 (synthesis) · Claude Haiku 4.5 (intent routing, NLI)  
**Embeddings / Rerank:** Cohere `embed-multilingual-v3.0` · `rerank-multilingual-v3.0`  
**Observability:** LangSmith — full trace tree with RAG, Hasura, and NLI spans

---

## Prerequisites

### API keys (required)
| Key | Where to get |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `COHERE_API_KEY` | https://dashboard.cohere.com |
| `LANGCHAIN_API_KEY` | https://smith.langchain.com (optional — for LangSmith tracing) |

### Software
| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 | Use pyenv if needed |
| PostgreSQL | 15+ | Must run on host (not Docker) — Hasura connects via `host.docker.internal` |
| Docker + Docker Compose | Latest | For Redis, OpenSearch, Neo4j, Hasura |

---

## 1 — Clone and create virtualenv

```bash
git clone https://github.com/sonnylai/AI-FrontLine-Agent.git
cd AI-FrontLine-Agent

python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 2 — Environment file

Copy the template and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# PostgreSQL (host machine)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ai_frontline_v2
POSTGRES_USER=admin
POSTGRES_PASSWORD=admin

# Hasura (Docker)
HASURA_URL=http://localhost:8080/v1/graphql
HASURA_ADMIN_SECRET=hasura-admin-secret-2026

# Redis (Docker)
REDIS_URL=redis://localhost:6379/0

# OpenSearch (Docker)
OPENSEARCH_URL=https://localhost:9200
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=Frontline2026@Xyz

# Neo4j (Docker)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=Frontline2026@Xyz

# Anthropic (required)
ANTHROPIC_API_KEY=sk-ant-...

# Cohere (required)
COHERE_API_KEY=...
COHERE_EMBED_MODEL=embed-multilingual-v3.0

# LangSmith (optional — set LANGCHAIN_TRACING_V2=false to disable)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=ai-frontline-agent

# JWT
JWT_SECRET_KEY=crm-jwt-secret-key-change-in-prod
```

> If you don't have a LangSmith account, set `LANGCHAIN_TRACING_V2=false`.

---

## 3 — PostgreSQL setup (host machine)

Install PostgreSQL 15+ and create the database:

```bash
psql -U postgres -c "CREATE USER admin WITH PASSWORD 'admin';"
psql -U postgres -c "CREATE DATABASE ai_frontline_v2 OWNER admin;"
psql -U admin -d ai_frontline_v2 -f scripts/schema.sql
```

---

## 4 — Start Docker services

```bash
docker compose up -d
```

This starts: **Redis** (6379) · **OpenSearch** (9200) · **OpenSearch Dashboards** (5601) · **Neo4j** (7474 / 7687) · **Hasura** (8080)

Wait ~30 seconds for OpenSearch to be ready, then verify:

```bash
docker compose ps        # all services should be "healthy"
```

---

## 5 — Seed data and configure Hasura

Run these scripts in order (each takes a few seconds):

```bash
# 1. Generate synthetic customer/transaction data
python scripts/generate_data.py

# 2. Seed PostgreSQL (customers, reps, accounts, transactions, contracts)
python scripts/seed_postgres.py

# 3. Seed Neo4j (customer → contract graph relationships)
python scripts/seed_neo4j.py

# 4. Configure Hasura (track all tables, set permissions, add relationships)
python scripts/setup_hasura.py

# 5. Create OpenSearch index with KNN mapping
python scripts/create_indexes.py

# 6. Embed and index product knowledge documents into OpenSearch
python scripts/ingest_docs.py
```

> `ingest_docs.py` calls Cohere's embedding API in batches — it takes ~2–3 minutes on first run. Subsequent re-runs re-index from scratch.

---

## 6 — Run the app

```bash
source .venv/bin/activate
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

Default login credentials (from seed data):

| Username | Password | Role |
|---|---|---|
| `rep001` | `password123` | Sales Rep |
| `rep002` | `password123` | Sales Rep |

---

## 7 — Verify the setup

```bash
# Run the full smoke test suite (37 checks)
python scripts/smoke_test.py
```

All 37 checks should pass. If any fail, the output will tell you which service or seed step is missing.

---

## Service URLs (after `docker compose up`)

| Service | URL | Notes |
|---|---|---|
| **API** | http://localhost:8000 | FastAPI + frontend |
| **API docs** | http://localhost:8000/docs | Swagger UI |
| **Hasura console** | http://localhost:8080/console | Admin secret: `hasura-admin-secret-2026` |
| **Neo4j browser** | http://localhost:7474 | user: `neo4j` / pw: `Frontline2026@Xyz` |
| **OpenSearch Dashboards** | http://localhost:5601 | user: `admin` / pw: `Frontline2026@Xyz` |

---

## Developer tools

### Trace the RAG pipeline (debug retrieval)

```bash
PYTHONPATH="." python scripts/rag_trace.py "các quỹ liên kết của sản phẩm Banca"
```

Prints all 5 stages: BM25 hits → KNN hits → RRF merge → Cohere rerank → sibling expansion.

### LangSmith trace view

After sending a chat message, open https://smith.langchain.com and find the project `ai-frontline-agent`. Each request creates one trace with the full span tree:

```
chat:CUST-001
└── _product_agent
│   ├── RAG·BM25 / RAG·KNN / RAG·RRF_Merge / RAG·Cohere_Rerank / RAG·Sibling_Expansion
│   └── NLI·PerAgent  {overlap_pct, verified}
└── aggregator
    ├── QueryDispatcher·Hasura  {query_type, variables_sent, rows_returned}
    ├── NLI·OutputGuardrail     {passed, triggered_rule}
    └── NLI·Final               {consistent, issues}
```

---

## Project structure

```
src/
├── api/              # FastAPI routers (auth, chat SSE, customers, sessions)
├── agents/
│   ├── nodes/        # intent_rewrite, aggregator LangGraph nodes
│   ├── orchestrator.py       # LangGraph StateGraph + fan-out routing
│   ├── query_dispatcher.py   # Hasura GraphQL templates (structured data)
│   ├── product_agent.py      # RAG → Sonnet → NLI
│   ├── contract_agent.py     # Neo4j + RAG → Sonnet → NLI
│   └── advisory_agent.py     # NBA logic + RAG → Sonnet → NLI
├── rag/
│   └── retriever.py  # BM25 + KNN → RRF → Cohere rerank → sibling expansion
├── cache/            # Redis session store + query cache
├── db/               # Hasura, Neo4j, OpenSearch, PostgreSQL clients
├── safety/           # NLI layers: nli_checker, output_guardrail, final_nli
└── config.py         # Pydantic settings (reads from .env)

scripts/
├── generate_data.py  # Generate synthetic seed data JSON
├── schema.sql        # PostgreSQL DDL
├── seed_postgres.py  # Load data/seeds/*.json into Postgres
├── seed_neo4j.py     # Build customer→contract graph in Neo4j
├── setup_hasura.py   # Track tables + configure permissions in Hasura
├── create_indexes.py # Create OpenSearch product-docs index
├── ingest_docs.py    # Chunk + embed + index data/documents/**/*.md
├── rag_trace.py      # Debug RAG retrieval pipeline
└── smoke_test.py     # 37-check integration test

data/
├── documents/        # Product knowledge markdown files (RAG source)
└── seeds/            # Generated JSON seed files
```

---

## Evaluation (offline, separate venv)

Ragas evaluation has a dependency conflict with LangGraph — install in a separate environment:

```bash
python3.12 -m venv .venv-eval
source .venv-eval/bin/activate
pip install -r requirements-eval.txt
```

Ragas metrics available: Faithfulness, Answer Relevancy, Context Precision, Context Recall.  
A golden dataset and eval runner script are not yet included — see `requirements-eval.txt` for details.
