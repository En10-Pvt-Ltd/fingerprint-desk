# SPDX-License-Identifier: Apache-2.0
"""Google OAuth (Authlib) + cookie sessions + route-guard dependencies.

The signed session cookie holds only {"uid", "csrf"}. Users land in the
SQLite users table on first login. Admins are flagged either in the DB
(users.is_admin) or via the ADMIN_EMAILS env var (comma-separated).

With FF_DEV_LOGIN=1 (never set in production) POST /auth/dev-login creates
and signs in a user without Google — used by selftest.py and local dev.
The shim hard-disables itself when Google OAuth is configured or BASE_URL
is https, so it cannot be switched on against a production deploy.
"""
import os
import secrets

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from engine import db

router = APIRouter()

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8765")
ADMIN_EMAILS = {e.strip().lower()
                for e in os.environ.get("ADMIN_EMAILS", "").split(",")
                if e.strip()}
DEV_LOGIN = (os.environ.get("FF_DEV_LOGIN") == "1"
             and not os.environ.get("GOOGLE_CLIENT_ID")
             and not BASE_URL.startswith("https"))

_oauth = None


def oauth():
    global _oauth
    if _oauth is None:
        cid = os.environ.get("GOOGLE_CLIENT_ID")
        secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        if not cid or not secret:
            raise HTTPException(503, "sign-in is not configured on this "
                                     "server (missing Google OAuth "
                                     "credentials)")
        from authlib.integrations.starlette_client import OAuth
        _oauth = OAuth()
        _oauth.register(
            name="google",
            client_id=cid, client_secret=secret,
            server_metadata_url="https://accounts.google.com/"
                                ".well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"})
    return _oauth


def _login(request: Request, user):
    request.session.clear()
    request.session["uid"] = user["id"]
    request.session["csrf"] = secrets.token_urlsafe(32)


def is_admin(user):
    return bool(user.get("is_admin")) or user["email"].lower() in ADMIN_EMAILS


# ---- routes -------------------------------------------------------------------
@router.get("/auth/login")
async def login(request: Request):
    redirect_uri = BASE_URL.rstrip("/") + "/auth/callback"
    return await oauth().google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback")
async def callback(request: Request):
    try:
        token = await oauth().google.authorize_access_token(request)
    except Exception:
        raise HTTPException(400, "sign-in failed; please try again")
    info = token.get("userinfo") or {}
    if not info.get("sub") or not info.get("email"):
        raise HTTPException(400, "Google did not return a usable identity")
    if info.get("email_verified") is False:
        raise HTTPException(400, "Google account email is unverified")
    user = db.upsert_user(info["sub"], info["email"], info.get("name"),
                          info.get("picture"))
    _login(request, user)
    return RedirectResponse("/")


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.post("/auth/dev-login")
def dev_login(request: Request, body: dict):
    if not DEV_LOGIN:
        raise HTTPException(404, "not found")
    email = (body or {}).get("email", "dev@example.com")
    user = db.upsert_user("dev-" + email, email, (body or {}).get("name"))
    _login(request, user)
    return {"ok": True, "user_id": user["id"]}


@router.get("/api/me")
def me(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "not signed in")
    return {"email": user["email"], "name": user["name"],
            "picture": user["picture"], "is_admin": is_admin(user),
            "csrf": request.session["csrf"]}


# ---- dependencies -------------------------------------------------------------
def current_user(request: Request):
    uid = request.session.get("uid")
    return db.get_user(uid) if uid else None


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "sign in first")
    return user


def require_admin(request: Request):
    user = require_user(request)
    if not is_admin(user):
        raise HTTPException(403, "admin only")
    return user


def csrf_check(request: Request):
    tok = request.headers.get("X-CSRF-Token")
    if not tok or not secrets.compare_digest(tok,
                                             request.session.get("csrf", "")):
        raise HTTPException(403, "missing or stale CSRF token; reload the "
                                 "page")
