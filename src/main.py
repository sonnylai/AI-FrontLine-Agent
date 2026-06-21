import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api import auth, chat, customers
from src.db import hasura_client, neo4j_client, opensearch_client, postgres
from src.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("afl")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting up — initialising database connections...")
    s = get_settings()

    await postgres.init_pool()
    log.info("PostgreSQL pool ready")

    hasura_client.init_client()
    log.info("Hasura client ready")

    await neo4j_client.init_driver()
    log.info("Neo4j driver ready")

    opensearch_client.init_client()
    log.info("OpenSearch client ready")

    log.info("All connections up — AI FrontLine Agent V2 is ready")
    yield

    log.info("Shutting down...")
    await postgres.close_pool()
    await hasura_client.close_client()
    await neo4j_client.close_driver()
    log.info("Shutdown complete")


app = FastAPI(
    title="AI FrontLine Agent V2",
    description="Intelligent banking sales assistant — RAG + LangGraph + multi-agent pipeline",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(customers.router)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "AI FrontLine Agent V2"}


# Serve frontend — must come last so API routes take priority
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
