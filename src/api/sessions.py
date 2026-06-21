"""
Session lifecycle endpoints.
  POST /sessions/start  — generate session_id, pre-warm Redis cache
  POST /sessions/end    — summarize conversation → OpenSearch, clear Redis
"""
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from src.middleware.jwt_auth import get_current_rep
from src.cache import session_store

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionStartRequest(BaseModel):
    customer_id: str


class SessionStartResponse(BaseModel):
    session_id: str
    customer_id: str


class SessionEndRequest(BaseModel):
    session_id:  str
    customer_id: str
    messages:    list[dict] = []    # full conversation: [{role, content}, ...]


@router.post("/start", response_model=SessionStartResponse)
async def start_session(
    req: SessionStartRequest,
    rep: dict = Depends(get_current_rep),
):
    session_id = f"{rep['sub']}-{req.customer_id}-{uuid.uuid4().hex[:8]}"

    # Pre-warm: load from Hasura + OpenSearch, cache in Redis
    await session_store.load(session_id, req.customer_id)

    return SessionStartResponse(session_id=session_id, customer_id=req.customer_id)


@router.post("/end", status_code=204)
async def end_session(
    req: SessionEndRequest,
    rep: dict = Depends(get_current_rep),
):
    # Summarize → OpenSearch, clear Redis
    await session_store.end(req.session_id, req.customer_id, req.messages)
