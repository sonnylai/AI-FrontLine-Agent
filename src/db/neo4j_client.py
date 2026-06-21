from neo4j import AsyncGraphDatabase, AsyncDriver
from src.config import get_settings

_driver: AsyncDriver | None = None


async def init_driver():
    global _driver
    s = get_settings()
    _driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    await _driver.verify_connectivity()


async def close_driver():
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _driver


async def run_query(cypher: str, params: dict | None = None) -> list[dict]:
    async with get_driver().session() as session:
        result = await session.run(cypher, params or {})
        return [dict(record) async for record in result]
