from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL
    postgres_host:     str = "localhost"
    postgres_port:     int = 5432
    postgres_db:       str = "ai_frontline_v2"
    postgres_user:     str = "admin"
    postgres_password: str = "admin"

    # Hasura
    hasura_url:          str = "http://localhost:8080/v1/graphql"
    hasura_admin_secret: str = "hasura-admin-secret-2026"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenSearch
    opensearch_url:      str = "https://localhost:9200"
    opensearch_user:     str = "admin"
    opensearch_password: str = ""

    # Neo4j
    neo4j_uri:      str = "bolt://localhost:7687"
    neo4j_user:     str = "neo4j"
    neo4j_password: str = ""

    # Anthropic
    anthropic_api_key:      str = ""
    anthropic_sonnet_model: str = "claude-sonnet-4-6-20251101"
    anthropic_haiku_model:  str = "claude-haiku-4-5-20251001"

    # Cohere
    cohere_api_key:    str = ""
    cohere_embed_model: str = "embed-multilingual-v3.0"

    # JWT  — must match HASURA_GRAPHQL_JWT_SECRET key in docker-compose.yml
    jwt_secret_key:     str = "crm-jwt-secret-key-change-in-prod"
    jwt_algorithm:      str = "HS256"
    jwt_expire_minutes: int = 480

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key:    str  = ""
    langchain_project:    str  = "ai-frontline-agent"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
