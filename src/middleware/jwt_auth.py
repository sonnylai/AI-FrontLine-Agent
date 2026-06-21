from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from src.config import get_settings

bearer = HTTPBearer()


def create_token(rep_id: str, full_name: str) -> str:
    """Generate a JWT that Hasura can verify (includes hasura claims namespace)."""
    from datetime import datetime, timedelta, timezone

    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  rep_id,
        "name": full_name,
        "iat":  now,
        "exp":  now + timedelta(minutes=s.jwt_expire_minutes),
        # Hasura reads claims from this namespace
        "https://hasura.io/jwt/claims": {
            "x-hasura-default-role":  "sales_rep",
            "x-hasura-allowed-roles": ["sales_rep"],
            "x-hasura-rep-id":        rep_id,
        },
    }
    return jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_rep(credentials: HTTPAuthorizationCredentials = Security(bearer)) -> dict:
    """FastAPI dependency — returns decoded JWT payload with rep_id."""
    return decode_token(credentials.credentials)
