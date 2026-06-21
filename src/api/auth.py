from fastapi import APIRouter, HTTPException, status
from src.db import postgres
from src.middleware.jwt_auth import create_token
from src.models.chat import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# Demo passwords — in production these would be hashed in the DB.
# Key: rep_id, Value: plain-text password for this demo.
DEMO_PASSWORDS = {f"REP-{i:03d}": "demo1234" for i in range(1, 11)}


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    expected = DEMO_PASSWORDS.get(body.rep_id)
    if not expected or body.password != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    pool = postgres.get_pool()
    row = await pool.fetchrow(
        "SELECT rep_id, full_name FROM sales_reps WHERE rep_id = $1 AND active = true",
        body.rep_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Rep not found or inactive")

    token = create_token(rep_id=row["rep_id"], full_name=row["full_name"])
    return LoginResponse(access_token=token, rep_id=row["rep_id"], full_name=row["full_name"])
