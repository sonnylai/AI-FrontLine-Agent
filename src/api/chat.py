import asyncio
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from src.middleware.jwt_auth import get_current_rep
from src.models.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


def sse(event: str, data: str | dict, agent: str | None = None, verified: bool | None = None) -> str:
    """Format a single SSE message."""
    payload = {"event": event, "data": data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)}
    if agent is not None:
        payload["agent"] = agent
    if verified is not None:
        payload["verified"] = verified
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def run_pipeline(request: ChatRequest, rep: dict):
    """
    Agent pipeline generator — yields SSE strings.
    Phase 3 will replace the placeholder body with real LangGraph execution.
    """
    yield sse("thinking", "Đang phân tích câu hỏi...")
    await asyncio.sleep(0.1)

    # ── Placeholder: intent classification ──────────────────────────────────
    yield sse("thinking", "Phân loại ý định: product_knowledge")
    await asyncio.sleep(0.1)

    # ── Placeholder: agent result ────────────────────────────────────────────
    yield sse(
        "agent_result",
        {
            "agent":    "product",
            "answer":   f"[Phase 3 pending] Câu hỏi: '{request.message}' — agent pipeline chưa được triển khai.",
            "sources":  [],
            "verified": False,
        },
        agent="product",
        verified=False,
    )

    # ── Placeholder: streamed synthesis tokens ───────────────────────────────
    answer = "Tính năng đang được phát triển. Pipeline LangGraph sẽ được tích hợp trong Phase 3."
    for token in answer:
        yield sse("token", token)
        await asyncio.sleep(0.01)

    yield sse("done", "")


@router.post("")
async def chat(request: ChatRequest, rep: dict = Depends(get_current_rep)):
    return StreamingResponse(
        run_pipeline(request, rep),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
