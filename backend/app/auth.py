from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
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


class GoogleCredential(BaseModel):
    credential: str = Field(min_length=10)


def create_session_for_user(conn, user, response: Response):
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
        return create_session_for_user(conn, user, response)


@router.get("/google/config")
def google_config():
    is_dev = settings().environment == "development"
    return {
        "enabled": bool(settings().google_client_id),
        "client_id": settings().google_client_id or "",
        "dev_mock": is_dev and not bool(settings().google_client_id),
        "allowed_domains": settings().google_allowed_domains,
    }


@router.post("/google")
def google_auth(body: GoogleCredential, response: Response):
    client_id = settings().google_client_id
    if not client_id:
        if settings().environment == "development" and body.credential.startswith("mock:"):
            mock_email = body.credential.removeprefix("mock:").strip().lower() or "demo.google@polaris.edu.in"
            mock_name = "Google Demo User"
            with connection() as conn:
                user = conn.execute(
                    "SELECT * FROM mis.accounts WHERE lower(username)=%s AND active", (mock_email,)
                ).fetchone()
                if not user:
                    uid = uuid4()
                    role = settings().google_default_role
                    if role not in {"admin", "operator", "viewer"}:
                        role = "viewer"
                    conn.execute(
                        """INSERT INTO mis.accounts (id, username, display_name, password_hash, role, active)
                           VALUES (%s, %s, %s, %s, %s, true)""",
                        (uid, mock_email, mock_name, dummy_hash, role),
                    )
                    user = conn.execute("SELECT * FROM mis.accounts WHERE id=%s", (uid,)).fetchone()
                return create_session_for_user(conn, user, response)

        raise HTTPException(
            503,
            "Google authentication is not configured on the server. Please set GOOGLE_CLIENT_ID in your .env file.",
        )
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        idinfo = id_token.verify_oauth2_token(body.credential, google_requests.Request(), client_id)
    except Exception as exc:
        raise HTTPException(401, f"Google token verification failed: {exc}")

    email = (idinfo.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Google account does not provide an email address.")
    if not idinfo.get("email_verified", True):
        raise HTTPException(401, "Google email address is not verified.")

    if settings().google_allowed_domains:
        domain = email.split("@")[-1]
        if domain not in settings().google_allowed_domains:
            allowed_fmt = ", ".join(f"@{d}" for d in settings().google_allowed_domains)
            raise HTTPException(
                403,
                f"Access restricted. Only institutional accounts from {allowed_fmt} are allowed.",
            )

    display_name = idinfo.get("name") or idinfo.get("given_name") or email.split("@")[0]

    with connection() as conn:
        user = conn.execute(
            "SELECT * FROM mis.accounts WHERE lower(username)=%s AND active", (email,)
        ).fetchone()
        if not user:
            uid = uuid4()
            role = settings().google_default_role
            if role not in {"admin", "operator", "viewer"}:
                role = "viewer"
            conn.execute(
                """INSERT INTO mis.accounts (id, username, display_name, password_hash, role, active)
                   VALUES (%s, %s, %s, %s, %s, true)""",
                (uid, email, display_name, dummy_hash, role),
            )
            user = conn.execute("SELECT * FROM mis.accounts WHERE id=%s", (uid,)).fetchone()

        return create_session_for_user(conn, user, response)


@router.get("/google/login")
def google_login_redirect(request: Request):
    client_id = settings().google_client_id
    if not client_id:
        raise HTTPException(
            503,
            "Google authentication is not configured. Please set GOOGLE_CLIENT_ID in your .env file.",
        )
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/auth/google/callback"
    state_payload = {"nonce": uuid4().hex, "exp": datetime.now(UTC) + timedelta(minutes=10)}
    state = jwt.encode(state_payload, settings().jwt_secret, algorithm="HS256")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    if error:
        raise HTTPException(400, f"Google login error: {error}")
    if not code or not state:
        raise HTTPException(400, "Missing Google authorization code or state")
    try:
        jwt.decode(state, settings().jwt_secret, algorithms=["HS256"])
    except Exception:
        raise HTTPException(400, "Invalid or expired state parameter")

    client_id = settings().google_client_id
    client_secret = settings().google_client_secret
    if not client_id or not client_secret:
        raise HTTPException(
            503,
            "Google client credentials are not fully configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/auth/google/callback"
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=10.0) as http_client:
        token_resp = http_client.post(token_url, data=token_data)
        if token_resp.status_code != 200:
            raise HTTPException(401, f"Failed to retrieve Google token: {token_resp.text}")
        token_json = token_resp.json()
        id_token_str = token_json.get("id_token")

    if not id_token_str:
        raise HTTPException(401, "Google did not return an ID token")

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        idinfo = id_token.verify_oauth2_token(id_token_str, google_requests.Request(), client_id)
    except Exception as exc:
        raise HTTPException(401, f"Google ID token verification failed: {exc}")

    email = (idinfo.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Google account does not provide an email address.")
    if not idinfo.get("email_verified", True):
        raise HTTPException(401, "Google email address is not verified.")

    if settings().google_allowed_domains:
        domain = email.split("@")[-1]
        if domain not in settings().google_allowed_domains:
            allowed_fmt = ", ".join(f"@{d}" for d in settings().google_allowed_domains)
            raise HTTPException(
                403,
                f"Access restricted. Only institutional accounts from {allowed_fmt} are allowed.",
            )

    display_name = idinfo.get("name") or idinfo.get("given_name") or email.split("@")[0]

    with connection() as conn:
        user = conn.execute(
            "SELECT * FROM mis.accounts WHERE lower(username)=%s AND active", (email,)
        ).fetchone()
        if not user:
            uid = uuid4()
            role = settings().google_default_role
            if role not in {"admin", "operator", "viewer"}:
                role = "viewer"
            conn.execute(
                """INSERT INTO mis.accounts (id, username, display_name, password_hash, role, active)
                   VALUES (%s, %s, %s, %s, %s, true)""",
                (uid, email, display_name, dummy_hash, role),
            )
            user = conn.execute("SELECT * FROM mis.accounts WHERE id=%s", (uid,)).fetchone()

        now = datetime.now(UTC)
        expiry = now + timedelta(hours=settings().session_hours)
        sid = uuid4()
        conn.execute(
            "INSERT INTO mis.sessions(id,account_id,expires_at) VALUES (%s,%s,%s)",
            (sid, user["id"], expiry),
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
        res = RedirectResponse("/", status_code=303)
        res.set_cookie(
            "polaris_session",
            token,
            httponly=True,
            secure=settings().cookie_secure,
            samesite="strict",
            max_age=settings().session_hours * 3600,
            path="/api",
        )
        return res


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
