import asyncpg
from src.config import get_settings

_pool: asyncpg.Pool | None = None


async def init_pool():
    global _pool
    s = get_settings()
    _pool = await asyncpg.create_pool(
        host=s.postgres_host,
        port=s.postgres_port,
        database=s.postgres_db,
        user=s.postgres_user,
        password=s.postgres_password,
        min_size=2,
        max_size=10,
    )


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialised")
    return _pool
