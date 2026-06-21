from typing import Optional, Literal
from pydantic import BaseModel


class ChatRequest(BaseModel):
    customer_id:          str
    message:              str
    session_id:           Optional[str] = None
    conversation_history: list[dict]   = []    # [{role, content}] — frontend owns this


class AgentResult(BaseModel):
    agent:    str                        # "product" | "contract" | "advisory"
    answer:   str
    sources:  list[str] = []            # chunk IDs or clause IDs used
    verified: bool = False              # per-agent NLI passed
    warning:  Optional[str] = None     # reason if not verified


class StreamEvent(BaseModel):
    event:    Literal["thinking", "token", "agent_result", "done", "error"]
    data:     str
    agent:    Optional[str] = None
    verified: Optional[bool] = None


class LoginRequest(BaseModel):
    rep_id:   str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    rep_id:       str
    full_name:    str
