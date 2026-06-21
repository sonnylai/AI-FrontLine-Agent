import asyncio
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from src.middleware.jwt_auth import get_current_rep
from src.models.chat import ChatRequest
from src.agents import orchestrator

router = APIRouter(prefix="/chat", tags=["chat"])


def sse(event: str, data: str | dict) -> str:
    payload = {
        "event": event,
        "data":  data if isinstance(data, str) else json.dumps(data, ensure_ascii=False),
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_pipeline(request: ChatRequest, rep: dict):
    queue: asyncio.Queue = asyncio.Queue()

    # Run pipeline in background — it writes events to the queue
    async def run():
        try:
            await orchestrator.run(
                customer_id=request.customer_id,
                rep_id=rep["sub"],
                message=request.message,
                session_id=request.session_id or f"{rep['sub']}-{request.customer_id}",
                conversation_history=request.conversation_history,
                stream_queue=queue,
            )
        except Exception as e:
            await queue.put(("error", str(e)))
            await queue.put(("done", "{}"))

    task = asyncio.create_task(run())

    # Read from queue and yield SSE
    while True:
        try:
            event_type, data = await asyncio.wait_for(queue.get(), timeout=60)
        except asyncio.TimeoutError:
            yield sse("error", "Pipeline timeout")
            break

        yield sse(event_type, data)

        if event_type in ("done", "error"):
            break

    await task


@router.post("")
async def chat(request: ChatRequest, rep: dict = Depends(get_current_rep)):
    return StreamingResponse(
        stream_pipeline(request, rep),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
