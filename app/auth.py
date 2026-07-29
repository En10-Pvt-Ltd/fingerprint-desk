# SPDX-License-Identifier: Apache-2.0
"""Cookie sessions, route-guard dependencies, and local-account auth.

Two modes, resolved by serve.resolve_mode() and stamped onto this module
at startup (serve sets auth.MODE):

- local  -- single-operator run bound to loopback. Every request acts as
  one implicit admin user (auth subject 'implicit'); there is no login
  screen, but a session cookie is still minted so csrf_check works
  unchanged.
- server -- email + password accounts (Argon2id via argon2-cffi). On a
  fresh server POST /auth/setup creates the first admin; everyone else
  joins through admin-created single-use invite links.

Hosted mode (OAuth sign-in for a multi-tenant deployment, e.g. Google) is
a future phase and is deliberately not built here.

The signed session cookie holds only {"uid", "csrf"}. ADMIN_EMAILS is a
bootstrap seed, NOT a live admin oracle: it may flag a signing-in user as
admin only while no admin exists at all (plus the one-time startup
migration db.seed_admins_from_env for pre-existing deployments). Once any
admin exists it never elevates anyone again -- admin lives solely in
users.is_admin.
"""
import collections
import datetime
import os
import secrets
import sqlite3
import threading
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, HTTPException, Request

from engine import db

router = APIRouter()

ADMIN_EMAILS = {e.strip().lower()
                for e in os.environ.get("ADMIN_EMAILS", "").split(",")
                if e.strip()}

# serve.py stamps the resolved FF_MODE here at startup. "server" is the
# fail-closed default: it demands credentials, whereas local mode would
# treat every caller as the implicit admin.
MODE = "server"

MIN_PASSWORD_LEN = 8
INVITE_TTL_DAYS = 7
LOGINS_PER_MIN = int(os.environ.get("FF_LOGINS_PER_MIN", 5))

_ph = PasswordHasher()          # Argon2id with the library defaults
_setup_lock = threading.Lock()

# Same sliding-window bucket as serve.rate_limit, replicated here to avoid
# an auth -> serve import cycle. Login-shaped routes are limited per client
# IP AND per submitted email, so neither one address nor one account can be
# hammered.
_buckets = collections.defaultdict(collections.deque)
_buckets_lock = threading.Lock()


def _rate_limit(key, per_min):
    now = time.monotonic()
    with _buckets_lock:
        q = _buckets[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_min:
            raise HTTPException(429, "too many sign-in attempts; wait a "
                                     "minute and try again")
        q.append(now)


def _client_ip(request):
    return request.client.host if request.client else "unknown"


def _login(request: Request, user):
    request.session.clear()     # session regeneration on every login
    request.session["uid"] = user["id"]
    request.session["csrf"] = secrets.token_urlsafe(32)


def is_admin(user):
    # users.is_admin is the ONLY admin source at request time. ADMIN_EMAILS
    # never grants admin here -- it is a bootstrap seed (_bootstrap_admin).
    return bool(user.get("is_admin"))


def _bootstrap_admin(user):
    """While NO admin exists at all, a signing-in user whose email is in
    ADMIN_EMAILS becomes the first admin. Once any admin exists this never
    elevates anyone again."""
    if (not user.get("is_admin") and db.count_admins() == 0
            and (user.get("email") or "").lower() in ADMIN_EMAILS):
        db.set_admin(user["id"])
        user = db.get_user(user["id"])
    return user


def _clean_email(body):
    email = str((body or {}).get("email") or "").strip().lower()
    if "@" not in email or len(email) > 254:
        raise HTTPException(400, "enter a valid email address")
    return email


def _check_password_ok(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"password must be at least "
                                 f"{MIN_PASSWORD_LEN} characters")


def _invite_valid(inv):
    if not inv or inv.get("used_utc"):
        return False
    try:
        created = datetime.datetime.fromisoformat(inv["created_utc"])
    except (TypeError, ValueError):
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return now - created <= datetime.timedelta(days=INVITE_TTL_DAYS)


# ---- routes -------------------------------------------------------------------
@router.post("/auth/setup")
def setup(request: Request, body: dict):
    """First run only (server mode): create the first admin account. Once
    any admin exists this route refuses forever."""
    if MODE != "server":
        raise HTTPException(404, "not found")
    email = _clean_email(body)
    password = (body or {}).get("password") or ""
    _check_password_ok(password)
    pw_hash = _ph.hash(password)
    with _setup_lock:
        if db.count_admins() > 0:
            raise HTTPException(409, "setup is already complete; sign in "
                                     "instead")
        try:
            user = db.create_local_user(email, pw_hash, is_admin=1)
        except sqlite3.IntegrityError:
            raise HTTPException(400, "that email cannot be used for setup")
    _login(request, user)
    return {"ok": True}


@router.post("/auth/login")
def login(request: Request, body: dict):
    if MODE != "server":
        raise HTTPException(404, "not found")
    email = str((body or {}).get("email") or "").strip().lower()
    password = (body or {}).get("password") or ""
    _rate_limit(("login-ip", _client_ip(request)), LOGINS_PER_MIN)
    _rate_limit(("login-email", email), LOGINS_PER_MIN)
    user = db.get_user_by_email(email)
    if user and user.get("password_hash"):
        try:
            _ph.verify(user["password_hash"], password)
        except VerifyMismatchError:
            user = None
        except Exception:       # malformed stored hash etc.: same outcome
            user = None
    else:
        user = None
    if user is None:
        # One generic message for unknown email / passwordless account /
        # wrong password: no user enumeration.
        raise HTTPException(401, "invalid email or password")
    try:
        if _ph.check_needs_rehash(user["password_hash"]):
            db.set_password(user["id"], _ph.hash(password))
    except Exception:
        pass                    # rehash is best-effort, never blocks login
    user = _bootstrap_admin(user)
    _login(request, user)
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.post("/api/admin/invite")
def invite(request: Request, body: dict):
    """Admin-only: mint a single-use invite link (valid INVITE_TTL_DAYS).
    Whether the email already has an account is never revealed here;
    accept-invite fails generically in that case."""
    if MODE != "server":
        raise HTTPException(404, "not found")
    user = require_admin(request)
    csrf_check(request)
    email = _clean_email(body)
    token = secrets.token_urlsafe(32)
    db.create_invite(token, email, user["id"])
    return {"ok": True, "invite_path": f"/#/invite/{token}",
            "email": email, "expires_days": INVITE_TTL_DAYS}


@router.post("/auth/accept-invite")
def accept_invite(request: Request, body: dict):
    if MODE != "server":
        raise HTTPException(404, "not found")
    _rate_limit(("login-ip", _client_ip(request)), LOGINS_PER_MIN)
    token = str((body or {}).get("token") or "")
    password = (body or {}).get("password") or ""
    bad = HTTPException(400, "this invite link is invalid, already used or "
                             "expired")
    inv = db.get_invite(token)
    if not _invite_valid(inv):
        raise bad
    _check_password_ok(password)
    email = inv["email"].strip().lower()
    if db.get_user_by_email(email):
        # Never reveal whether an email already has an account: the same
        # generic message as any other unusable invite.
        raise bad
    if not db.consume_invite(token):    # atomic single-use
        raise bad
    try:
        user = db.create_local_user(email, _ph.hash(password), is_admin=0)
    except sqlite3.IntegrityError:
        raise bad
    _login(request, user)
    return {"ok": True}


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
    if MODE == "local":
        # Single implicit admin (created on first need). A session cookie
        # is still minted so csrf_check keeps working exactly as in server
        # mode.
        user = db.ensure_implicit_user()
        if request.session.get("uid") != user["id"] \
                or "csrf" not in request.session:
            _login(request, user)
        return user
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
