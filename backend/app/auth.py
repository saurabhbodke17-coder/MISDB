from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, Field

from .config import settings
from .db import connection, one

router = APIRouter(prefix="/auth", tags=["Authentication"])
passwords = PasswordHash.recommended()
dummy_hash = passwords.hash("timing-equalization-not-a-login-password")


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


def current_user(request: Request):
    try:
        claims = jwt.decode(
            request.cookies.get("polaris_session", ""),
            settings().jwt_secret,
            algorithms=["HS256"],
            audience="polaris-mis",
            issuer="polaris-api",
        )
        user = one(
            """SELECT a.id, a.username, a.display_name, a.role FROM mis.accounts a
                   JOIN mis.sessions s ON s.account_id=a.id
                   WHERE s.id=%s AND a.id=%s AND a.active AND s.revoked_at IS NULL AND s.expires_at>now()""",
            (claims["jti"], claims["sub"]),
        )
        if user:
            return user
    except (jwt.InvalidTokenError, KeyError, ValueError):
        pass
    raise HTTPException(401, "Sign in to continue")


def editor(user=Depends(current_user)):
    if user["role"] not in {"admin", "operator"}:
        raise HTTPException(403, "An operator or administrator account is required")
    return user


def admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


@router.post("/login")
def login(body: Login, response: Response):
    username = body.username.strip().lower()
    with connection() as conn:
        # Serialize attempts for a username across processes before checking the limit.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (username,))
        attempts = conn.execute(
            """SELECT count(*) AS n FROM mis.login_attempts
                                WHERE username=%s AND NOT success AND attempted_at>now()-interval '15 minutes'""",
            (username,),
        ).fetchone()["n"]
        if attempts >= 10:
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        user = conn.execute("SELECT * FROM mis.accounts WHERE username=%s AND active", (username,)).fetchone()
        valid = passwords.verify(body.password, user["password_hash"] if user else dummy_hash)
        conn.execute(
            "INSERT INTO mis.login_attempts(username,success) VALUES (%s,%s)",
            (username, bool(user and valid)),
        )
        if not user or not valid:
            conn.commit()  # Persist failed attempts before returning the error.
            raise HTTPException(401, "Invalid username or password")
        conn.execute("DELETE FROM mis.login_attempts WHERE username=%s", (username,))
        now = datetime.now(UTC)
        expiry = now + timedelta(hours=settings().session_hours)
        sid = uuid4()
        conn.execute(
            "INSERT INTO mis.sessions(id,account_id,expires_at) VALUES (%s,%s,%s)", (sid, user["id"], expiry)
        )
        token = jwt.encode(
            {
                "sub": str(user["id"]),
                "jti": str(sid),
                "iat": now,
                "exp": expiry,
                "aud": "polaris-mis",
                "iss": "polaris-api",
            },
            settings().jwt_secret,
            algorithm="HS256",
        )
        response.set_cookie(
            "polaris_session",
            token,
            httponly=True,
            secure=settings().cookie_secure,
            samesite="strict",
            max_age=settings().session_hours * 3600,
            path="/api",
        )
        return {k: user[k] for k in ("id", "username", "display_name", "role")}


@router.get("/me")
def me(user=Depends(current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, user=Depends(current_user)):
    claims = jwt.decode(
        request.cookies["polaris_session"],
        settings().jwt_secret,
        algorithms=["HS256"],
        audience="polaris-mis",
        issuer="polaris-api",
    )
    with connection() as conn:
        conn.execute(
            "UPDATE mis.sessions SET revoked_at=now() WHERE id=%s AND account_id=%s",
            (claims["jti"], user["id"]),
        )
    response.delete_cookie("polaris_session", path="/api")
