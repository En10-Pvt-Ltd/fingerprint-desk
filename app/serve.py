#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fingerprint Desk: public crowdsourcing app over the research pipeline.

    pip install -r app/requirements.txt
    python app/serve.py          ->  http://localhost:8765

Flow: sign in (server mode: local email+password accounts; local mode: an
implicit operator) -> upload a PDF (or paste text) -> generate up to
FF_MAX_VARIANTS fingerprinted variants + one unmarked control -> print one
variant -> photograph it -> upload the photo -> plain-language attribution
verdict -> the contributor says Correct / Wrong (they know which variant
they printed), which is the crowdsourced ground-truth label. Artifacts land
as plain files under appdata/tests/; users/ownership/feedback live in
SQLite (engine/db.py).
"""
import collections
import datetime
import ipaddress
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import traceback

from fastapi import (Depends, FastAPI, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from PIL import Image
import uvicorn

import secrets

from engine import (APPDATA, REPO, store, render, scan, channel_sim,
                    render_pdf, scan_pdf, scan_raster, db, jobs, packs,
                    recovery, commitment)
import auth


def _runner_for(manifest):
    """Attribution runner by carrier type."""
    return {"pdf_preserved": scan_pdf,
            "pdf_raster": scan_raster,
            "pdf_vector": scan_raster}.get(manifest.get("type"), scan)

log = logging.getLogger("fingerprint-desk")
logging.basicConfig(level=logging.INFO)

UPLOADS = os.path.join(APPDATA, "uploads")

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Fingerprint Desk")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8765")
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    log.warning("SECRET_KEY not set; sessions will not survive a restart")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY,
                   same_site="lax", https_only=BASE_URL.startswith("https"))
app.include_router(auth.router)


# ---- deployment mode ----------------------------------------------------------
def _is_loopback_host(host):
    """True only for a host that is provably loopback ('localhost' or a
    loopback IP literal). Anything unparsable is NOT loopback."""
    host = (host or "").strip()
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_mode():
    """FF_MODE -> 'local' | 'server' (see MIGRATION.md).

    local  = single operator on a loopback bind, no accounts (an implicit
             admin); the bind is enforced by GuardedServer below.
    server = network deployment with local email+password accounts.

    An unset FF_MODE is accepted only when the configuration is
    unambiguously local (loopback HOST, non-https BASE_URL); anything else
    refuses to start rather than silently exposing an open app or silently
    changing auth behavior."""
    mode = (os.environ.get("FF_MODE") or "").strip().lower()
    if mode == "hosted":
        raise SystemExit("FF_MODE=hosted: hosted mode is not available in "
                         "this build. Use FF_MODE=server.")
    if mode in ("local", "server"):
        return mode
    if mode:
        raise SystemExit(f"FF_MODE={mode!r} is not a mode; set FF_MODE=local "
                         "or FF_MODE=server.")
    host = os.environ.get("HOST", "127.0.0.1")
    if BASE_URL.lower().startswith("https") or not _is_loopback_host(host):
        raise SystemExit(
            f"FF_MODE is not set, and HOST={host!r} / BASE_URL={BASE_URL!r} "
            "looks like a network deployment. Set FF_MODE=server for a "
            "network deployment; see MIGRATION.md. (FF_MODE=local is only "
            "for a private run on this machine.)")
    return "local"


def _assert_loopback(addresses, mode):
    """Local-mode bind guard, pure so the selftest can exercise it.

    `addresses` are the getsockname() host strings of the REAL bound
    sockets. Any non-loopback address -- or any ambiguity (no sockets, an
    address that does not parse) -- is fatal, never permissive: local mode
    must never serve beyond this machine."""
    if mode != "local":
        return
    if not addresses:
        raise SystemExit("local mode: no bound socket could be inspected; "
                         "refusing to serve. Set FF_MODE=server for a "
                         "network deployment (see MIGRATION.md).")
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(str(addr).split("%")[0])
        except ValueError:
            raise SystemExit(f"local mode: bound address {addr!r} is not a "
                             "plain IP address; refusing to serve.")
        if not ip.is_loopback:
            raise SystemExit(f"local mode is loopback-only, but the server "
                             f"is bound to {addr}. Set FF_MODE=server for a "
                             "network deployment (see MIGRATION.md).")


class GuardedServer(uvicorn.Server):
    """uvicorn.Server that inspects the REAL bound sockets after the bind:
    in local mode any non-loopback socket -- or a socket set that cannot be
    inspected at all -- kills the process. Checking after the bind (instead
    of trusting the requested host string) covers every configuration path,
    including dual-stack and hostname binds. Defined at module scope so the
    selftest can drive startup() directly and prove the server refuses, not
    just that the _assert_loopback helper is correct."""

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        self.assert_bound_loopback()

    def assert_bound_loopback(self):
        """The guard proper, split out so the selftest can drive it with a
        controlled socket set (proving the server refuses, not just that the
        helper is correct) without opening a real socket."""
        if MODE != "local":
            return
        try:
            addrs = [str(s.getsockname()[0])
                     for srv in (self.servers or [])
                     for s in (srv.sockets or [])]
        except (OSError, IndexError, TypeError):
            raise SystemExit("local mode: could not inspect the bound "
                             "sockets; refusing to serve. Set "
                             "FF_MODE=server for a network deployment.")
        _assert_loopback(addrs, MODE)


MODE = resolve_mode()
auth.MODE = MODE                # auth branches on the resolved mode
# ADMIN_EMAILS upgrade migration: flag every EXISTING user named there so
# active admins keep admin; from now on it only seeds (never a live check).
db.seed_admins_from_env(auth.ADMIN_EMAILS)

MAX_VARIANTS = int(os.environ.get("FF_MAX_VARIANTS", 5))
MAX_CAMPAIGN_VARIANTS = int(os.environ.get("FF_MAX_CAMPAIGN_VARIANTS", 300))
MAX_WORDS = 20000
MAX_PDF_MB = 20
MAX_PDF_PAGES = int(os.environ.get("FF_MAX_PDF_PAGES", 10))
MAX_PHOTO_MB = 15
MAX_SCAN_PIXELS = 60_000_000     # 60 MP: above any phone sensor, far below
                                 # the decode-bomb range
# Floor on the longest side of an uploaded photo: the 300-variant
# simulation showed sub-1200px captures carry too little geometry to read
# reliably (both wrong-variant cases were 1000px), while WhatsApp's ~1600px
# recompression passes comfortably.
MIN_CAPTURE_PX = int(os.environ.get("FF_MIN_CAPTURE_PX", 1200))
QUOTA_TESTS_PER_DAY = int(os.environ.get("FF_QUOTA_TESTS_PER_DAY", 5))
QUOTA_SCANS_PER_DAY = int(os.environ.get("FF_QUOTA_SCANS_PER_DAY", 30))
UPLOADS_PER_MIN = int(os.environ.get("FF_UPLOADS_PER_MIN", 5))

CAPTURE_ENUMS = {
    "printer": ["laser_mono", "laser_color", "inkjet", "unknown"],
    "phone": ["budget", "mid", "flagship", "unknown"],
    "lighting": ["office", "dim", "flash_glare", "window_backlight",
                 "unknown"],
    "framing": ["full", "half", "unknown"],
    "angle": ["0", "15", "30", "45", "unknown"],
}

require_user = auth.require_user
require_admin = auth.require_admin
csrf_check = auth.csrf_check


# ---- limits helpers -----------------------------------------------------------
async def read_limited(file: UploadFile, max_mb: int, what: str) -> bytes:
    cap = max_mb * 1024 * 1024
    chunks, size = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > cap:
            raise HTTPException(413, f"{what} larger than {max_mb} MB")
        chunks.append(chunk)
    return b"".join(chunks)


_buckets = collections.defaultdict(collections.deque)
_buckets_lock = threading.Lock()


def rate_limit(user_id, key, per_min):
    now = time.monotonic()
    with _buckets_lock:
        q = _buckets[(user_id, key)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_min:
            raise HTTPException(429, "too many requests; wait a minute and "
                                     "try again")
        q.append(now)


def campaign_capacity_warning(n_variants, n_pages):
    """Collision-risk sanity check for large campaigns.

    Line-shift only, full-page framing: a capture observes roughly
    B = 15 * n_pages coded bits (per the research pipeline: ~15 line bits
    per rendered page). An unrelated variant's codeword agrees with the
    captured one per-bit with p = 0.5, so the chance that at least one of
    n_variants innocent codewords crosses the ~0.93 attribution accuracy
    is bounded by n_variants * P(Binomial(B, 0.5) >= ceil(0.93 * B)).
    Returns a plain-language warning when that bound exceeds 1%, else None.
    """
    if not n_pages or not n_variants:
        return None
    B = 15 * n_pages
    t = math.ceil(0.93 * B)
    p_tail = sum(math.comb(B, k) for k in range(t, B + 1)) / 2 ** B
    risk = n_variants * p_tail
    if risk <= 0.01:
        return None
    max_safe = int(0.01 / p_tail) if p_tail > 0 else n_variants
    return (f"With {n_variants} variants on a {n_pages}-page document "
            f"(about {B} observable line bits per capture), there is "
            f"roughly a {min(risk, 1.0) * 100:.1f}% chance that some "
            f"variant nobody printed matches a leaked photo well enough "
            f"to be falsely accused. For a {n_pages}-page document keep "
            f"the campaign to at most {max_safe} variants, or use a "
            f"longer document.")


def check_quota(user, kind, per_day):
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=1)).isoformat()
    if db.count_events(user["id"], kind, since) >= per_day:
        raise HTTPException(429, f"daily limit reached ({per_day} "
                                 f"{kind}s/day); come back tomorrow")


# ---- models -------------------------------------------------------------------
class LayoutReq(BaseModel):
    content: str


class CreateReq(BaseModel):
    name: str
    content: str = ""
    variant_labels: list[str] = []   # join campaigns; roster derives from recipients
    n_controls: int = 1
    sample_used: bool = False
    mode: str = "rendered"          # "rendered" | "pdf_preserved"
    upload_id: str | None = None    # required for pdf_preserved
    # Phase 4 roster campaigns: the who-received-which mapping is fixed at
    # creation, so the campaign seals pre_distribution.
    distribution: str = "join"       # "join" | "roster"
    roster_mode: str | None = None   # "count" | "roster"
    identity_scheme: str | None = None   # "email" | "label"
    recipients: list[str] | None = None  # roster identities (raw), one per copy
    contacts: list[str] | None = None    # optional unsealed contact, parallel
    allow_duplicates: bool = False       # explicit confirm for duplicate identities


class SimulateReq(BaseModel):
    doc_id: str
    page_index: int = 0
    preset: str = "whatsapp"


class FeedbackReq(BaseModel):
    judgment: str                   # "correct" | "wrong" | "unsure"
    true_doc_id: str | None = None  # required when "wrong"
    note: str = ""


# ---- api ----------------------------------------------------------------------
@app.get("/api/config")
def config():
    return {"max_variants": MAX_VARIANTS, "capture_enums": CAPTURE_ENUMS,
            "mode": MODE,
            "needs_setup": MODE == "server" and db.count_admins() == 0}


@app.get("/api/sample")
def sample(user=Depends(require_user)):
    return {"content": render.SAMPLE_TEXT}


@app.post("/api/layout")
def layout(req: LayoutReq, user=Depends(require_user),
           _=Depends(csrf_check)):
    if not req.content.strip():
        raise HTTPException(400, "content is empty")
    if len(req.content.split()) > MAX_WORDS:
        raise HTTPException(400, f"content too long (max {MAX_WORDS} words)")
    return render.dry_layout(req.content)


def _pdf_worker(args, timeout):
    """Run engine.pdf_worker in a child process: pikepdf/pymupdf parse
    attacker-supplied bytes, and a crafted PDF that segfaults the parser
    must kill the child, not this server. The child rlimits its own memory;
    we bound its wall time here."""
    import subprocess
    import sys as _sys
    # Scrubbed environment: the child parses attacker bytes and must not
    # inherit SECRET_KEY or other secrets. FF_* is non-secret app
    # config the engine reads (FF_APPDATA, FF_FONT_PATH). Env names are
    # case-insensitive on Windows, so match on upper().
    _KEEP = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
             "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG",
             "LC_ALL", "PYTHONIOENCODING")
    env = {k: v for k, v in os.environ.items()
           if k.upper() in _KEEP or k.upper().startswith("FF_")}
    try:
        proc = subprocess.run([_sys.executable, "-m", "engine.pdf_worker",
                               *args], cwd=HERE, capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise HTTPException(400, "this PDF took too long to process; try a "
                                 "simpler document")
    return _worker_result(proc.returncode, (proc.stdout or "").strip(),
                          proc.stderr or "")


def _worker_result(returncode, stdout, stderr):
    """Interpret an engine.pdf_worker run. The child prints one JSON object
    on success or expected rejection; a crash prints nothing (a SIGSEGV from
    hitting RLIMIT_AS on Linux leaves stdout AND stderr empty). Distinguish
    the failure modes so the caller gets an actionable message instead of a
    bare 'could not be processed'."""
    lines = stdout.splitlines()
    if lines:
        try:
            out = json.loads(lines[-1])
        except ValueError:
            out = None
        if isinstance(out, dict):
            if not out.get("ok"):
                raise HTTPException(400, out.get("error", "PDF rejected"))
            return out
    stderr = stderr.strip()
    log.error("pdf worker failed (exit %s): %s", returncode, stderr[-2000:])
    if returncode is not None and returncode < 0:
        # killed by signal -returncode (SIGSEGV/SIGKILL/SIGABRT). On Linux
        # this is almost always the address-space limit on a large/complex
        # PDF, not the PDF itself.
        raise HTTPException(400,
            f"the PDF processor was stopped by the system (signal "
            f"{-returncode}) before it finished — usually the memory limit "
            "on a large or complex PDF. An administrator can raise "
            "FF_PDF_WORKER_MEM_MB; otherwise try a smaller or simpler "
            "document.")
    if returncode:
        tail = stderr.splitlines()[-1][:200] if stderr else ""
        raise HTTPException(400, "the PDF processor exited with an error"
                            + (f": {tail}" if tail else "")
                            + ". Try another document.")
    raise HTTPException(400, "the PDF processor returned no readable result; "
                            "try another document.")


async def _pdf_upload(file, user, mode):
    rate_limit(user["id"], "upload", UPLOADS_PER_MIN)
    data = await read_limited(file, MAX_PDF_MB, "PDF")
    os.makedirs(UPLOADS, exist_ok=True)
    upload_id = "up-" + secrets.token_hex(6)
    path = os.path.join(UPLOADS, upload_id + ".pdf")
    with open(path, "wb") as f:
        f.write(data)
    try:
        out = _pdf_worker([mode, path], timeout=60)
    except HTTPException:
        os.remove(path)
        raise
    if out["extract"]["pdf_pages"] > MAX_PDF_PAGES:
        os.remove(path)
        raise HTTPException(400, f"PDF has {out['extract']['pdf_pages']} "
                                 f"pages; this demo accepts up to "
                                 f"{MAX_PDF_PAGES}")
    return upload_id, path, out


@app.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile = File(...),
                      user=Depends(require_user), _=Depends(csrf_check)):
    """Stage 1: PDF as content source. Text is re-flowed through the app's
    layout engine; original formatting is not preserved."""
    _uid, path, out = await _pdf_upload(file, user, "extract")
    os.remove(path)                     # content is all we needed
    res = out["extract"]
    res["note"] = ("Text extracted and re-flowed through the app's layout "
                   "engine; the original PDF formatting is not preserved.")
    return res


@app.post("/api/analyze-pdf")
async def analyze_pdf(file: UploadFile = File(...),
                      user=Depends(require_user), _=Depends(csrf_check)):
    """Stage 2: analyze an uploaded PDF for formatting-preserving
    fingerprinting; stash it under an upload_id for test creation."""
    upload_id, path, out = await _pdf_upload(file, user, "analyze")
    mode = out.get("mode", "pdf_preserved")
    if mode in ("pdf_raster", "pdf_vector"):
        # No-text carriers: raster marks the page images of a scan;
        # vector translates outline-text paths (both field-validated).
        with open(os.path.join(UPLOADS, upload_id + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump({"pdf_pages": out["extract"]["pdf_pages"],
                       "mode": mode}, f)
        note = ("scanned/image-only PDF detected: the fingerprint will be "
                "embedded in the page images themselves (raster "
                "line-shift); tables, figures and stamps stay "
                "pixel-identical") if mode == "pdf_raster" else (
                "outline-text PDF detected (glyphs converted to vector "
                "paths): whole text lines are translated by a quarter "
                "millimetre in the drawing commands; vector quality is "
                "preserved exactly")
        return {"upload_id": upload_id, "filename": file.filename,
                "mode": mode, **out["raster"], "note": note}
    cap = out["cap"]
    if cap["total_bits"] == 0:
        os.remove(path)
        raise HTTPException(400,
            "no markable text bands: the mark needs runs of 3+ regular "
            f"body-text lines with pitch >= {cap['min_pitch_pt']} pt. "
            "Dense/tight leading or tables-only pages cannot carry the "
            "line-shift fingerprint.")
    # Sidecar for create_test: page count for the capacity warning without
    # re-parsing the untrusted PDF in this process.
    with open(os.path.join(UPLOADS, upload_id + ".json"), "w",
              encoding="utf-8") as f:
        json.dump({"pdf_pages": out["extract"]["pdf_pages"]}, f)
    return {"upload_id": upload_id, "filename": file.filename,
            "mode": mode, **cap}


@app.get("/api/tests")
def tests(user=Depends(require_user)):
    out = []
    for tid in db.user_test_ids(user["id"]):
        try:
            m = store.load_manifest(tid)
        except FileNotFoundError:
            continue
        m["n_scans"] = len(store.list_scans(tid))
        out.append(m)
    return out


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_roster(req, variant_cap):
    """Validate a roster/count campaign server-side (never trust the client's
    review gate): returns (labels, sealed, contacts). `labels` are the raw copy
    names; `sealed` are the normalised identities that go into the digest;
    duplicates are refused unless allow_duplicates is set (the server-side twin
    of the UI confirm)."""
    if req.roster_mode not in ("count", "roster"):
        raise HTTPException(400, "roster_mode must be 'count' or 'roster'")
    scheme = req.identity_scheme or "label"
    if scheme not in ("email", "label"):
        raise HTTPException(400, "identity_scheme must be 'email' or 'label'")
    recips = [r for r in (req.recipients or [])]
    if not 1 <= len(recips) <= variant_cap:
        raise HTTPException(400, f"a roster needs 1..{variant_cap} recipients")
    contacts = req.contacts if req.contacts is not None else [None] * len(recips)
    if len(contacts) != len(recips):
        raise HTTPException(400, "contacts must be parallel to recipients")
    sealed = []
    for i, raw in enumerate(recips):
        s = commitment.normalize_recipient(raw)
        if not s:
            raise HTTPException(400, f"recipient on row {i + 1} is empty")
        if scheme == "email" and not _EMAIL_RE.match(s):
            raise HTTPException(400, f"row {i + 1} is not a valid email: {raw!r}")
        sealed.append(s)
    dups = sorted({s for s in sealed if sealed.count(s) > 1})
    if dups and not req.allow_duplicates:
        raise HTTPException(400, detail={
            "code": "duplicate_recipients",
            "message": "the roster has duplicate identities; confirm to allow "
                       "more than one copy per recipient",
            "duplicates": dups})
    return recips, sealed, contacts


@app.post("/api/tests")
def create_test(req: CreateReq, user=Depends(require_user),
                _=Depends(csrf_check)):
    if not req.name.strip():
        raise HTTPException(400, "name required")
    # Admins may run large assigned campaigns; self-serve keeps the small cap
    variant_cap = MAX_CAMPAIGN_VARIANTS if auth.is_admin(user) \
        else MAX_VARIANTS
    # A roster campaign fixes recipients at creation (pre_distribution seal);
    # it is a controller feature, so it is admin-only and uses the full cap.
    is_roster = req.distribution == "roster"
    roster_sealed = roster_contacts = None
    if is_roster:
        if not auth.is_admin(user):
            raise HTTPException(403, "roster campaigns are an admin feature")
        labels, roster_sealed, roster_contacts = _validate_roster(req,
                                                                  variant_cap)
    else:
        labels = req.variant_labels
        if not 1 <= len(labels) <= variant_cap:
            raise HTTPException(400, f"1..{variant_cap} variants")
    req.variant_labels = labels
    check_quota(user, "test", QUOTA_TESTS_PER_DAY)   # per test, not variant
    n_controls = 1      # the unmarked control is the credibility check;
                        # public mode pins it to exactly one
    if req.mode not in ("rendered", "pdf_preserved", "pdf_raster",
                        "pdf_vector"):
        raise HTTPException(400, "bad mode")
    pdf_path = source_filename = None
    if req.mode in ("pdf_preserved", "pdf_raster", "pdf_vector"):
        if not req.upload_id or not store.valid_id(req.upload_id):
            raise HTTPException(400, "upload_id missing; re-upload the PDF")
        pdf_path = os.path.join(UPLOADS, req.upload_id + ".pdf")
        if not os.path.exists(pdf_path):
            raise HTTPException(400, "upload expired; re-upload the PDF")
        source_filename = req.upload_id
    elif not req.content.strip():
        raise HTTPException(400, "content required")
    elif len(req.content.split()) > MAX_WORDS:
        raise HTTPException(400, f"content too long (max {MAX_WORDS} words)")

    # Capacity warning needs the page count. Text mode: one dry layout pass.
    # PDF mode: the analyze step left a {upload_id}.json sidecar with the
    # page count (never re-parse the untrusted PDF in this process). The
    # sidecar also records the TRUE carrier the analyze worker detected for
    # no-text PDFs ("mode"); it is authoritative over the client's claim —
    # a preserved-capable sidecar has no "mode" key, so it defaults to
    # pdf_preserved.
    n_pages = None
    mode = req.mode
    try:
        if req.mode in ("pdf_preserved", "pdf_raster", "pdf_vector"):
            side = os.path.join(UPLOADS, req.upload_id + ".json")
            if os.path.exists(side):
                with open(side, encoding="utf-8") as f:
                    sidecar = json.load(f)
                n_pages = sidecar.get("pdf_pages")
                mode = sidecar.get("mode", "pdf_preserved")
        else:
            n_pages = render.dry_layout(req.content)["pages"]
    except Exception:
        log.exception("page-count estimate failed for capacity warning")
    warning = campaign_capacity_warning(len(req.variant_labels), n_pages)

    # A 300-variant PDF campaign embeds+rasterizes each variant serially;
    # a fixed 300 s wall would kill legitimate large generations. PDF
    # carriers also scale with the page count (each variant embeds and
    # rasterizes every page), so fold n_pages in; the cap is only an upper
    # wall bound, so being generous is fine.
    if mode in ("pdf_preserved", "pdf_raster", "pdf_vector"):
        gen_timeout = max(300, 8 * (len(req.variant_labels) + 1)
                          * max(1, n_pages or 1))
    else:
        gen_timeout = max(300, 10 * len(req.variant_labels))

    test_id = store.new_test_id(req.name)
    store.save_manifest({"test_id": test_id, "name": req.name,
                         "created_utc": store.now_utc(),
                         "status": "generating", "type": mode,
                         "n_docs": len(req.variant_labels) + n_controls})
    db.add_test(test_id, user["id"], mode, len(req.variant_labels))
    db.add_event(user["id"], "test")

    def work():
        try:
            if mode in ("pdf_preserved", "pdf_raster", "pdf_vector"):
                spec = {"name": req.name, "pdf_path": pdf_path,
                        "variant_labels": req.variant_labels,
                        "n_controls": n_controls, "test_id": test_id,
                        "mode": mode,
                        "source_filename": source_filename}
                specfile = os.path.join(store.test_dir(test_id), "spec.json")
                with open(specfile, "w", encoding="utf-8") as f:
                    json.dump(spec, f)
                _pdf_worker(["generate", specfile], timeout=gen_timeout)
                os.remove(specfile)
            else:
                render.generate_test(req.name, req.content,
                                     req.variant_labels, n_controls,
                                     req.sample_used, test_id)
            if is_roster:
                # Bind + seal the who-received-which mapping at creation: copy
                # v(i+1) -> the i-th recipient. This is the ONLY place a roster
                # is written; a roster campaign is frozen from here (no route
                # extends it, and share/join refuse it), so the pre_distribution
                # seal cannot be silently weakened after it is relied upon.
                db.record_roster(
                    test_id, req.roster_mode, req.identity_scheme or "label",
                    [(f"v{i + 1}", roster_sealed[i], roster_contacts[i])
                     for i in range(len(roster_sealed))])
            db.set_test_status(test_id, "generated")
        except Exception as e:
            log.exception("generation failed for %s", test_id)
            m = store.load_manifest(test_id)
            m.update({"status": "error", "error": str(e),
                      "trace": traceback.format_exc()})
            store.save_manifest(m)
            db.set_test_status(test_id, "error")

    jobs.submit_generation(work)
    return {"test_id": test_id, "status": "generating",
            "capacity_warning": warning}


def _is_owner(test_id, user):
    return db.test_owner(test_id) == user["id"] or auth.is_admin(user)


def _manifest(test_id, user, allow_shared=False):
    """Load a manifest the caller may access: their own test, any test for
    admins, or (when allow_shared) a campaign test shared with everyone."""
    if not store.valid_id(test_id):
        raise HTTPException(404, "no such test")
    owner = db.test_owner(test_id)
    if owner is None:
        raise HTTPException(404, "no such test")
    if not _is_owner(test_id, user) and not (allow_shared
                                             and db.is_shared(test_id)):
        raise HTTPException(404, "no such test")
    try:
        return store.load_manifest(test_id)
    except FileNotFoundError:
        raise HTTPException(404, "no such test")


@app.get("/api/campaigns")
def campaigns(user=Depends(require_user)):
    """Shared tests every contributor can print/photograph: the researcher
    uploads the PDF once, contributors skip straight to the print step."""
    out = []
    for tid in db.campaign_test_ids():
        try:
            m = store.load_manifest(tid)
        except FileNotFoundError:
            continue
        out.append({"test_id": tid, "name": m["name"],
                    "created_utc": m["created_utc"],
                    "n_variants": sum(1 for d in m.get("docs", [])
                                      if d["marked"]),
                    "n_my_scans": len(db.user_scan_ids(tid, user["id"]))})
    return out


@app.post("/api/campaigns/{test_id}/join")
def join_campaign(test_id: str, user=Depends(require_user),
                  _=Depends(csrf_check)):
    """Assigned-campaign join: hand this contributor the lowest unassigned
    MARKED variant (controls are never assigned). Idempotent: re-joining
    returns the existing assignment."""
    if not store.valid_id(test_id) or db.test_owner(test_id) is None:
        raise HTTPException(404, "no such campaign")
    # Refuse roster/imported campaigns with a clear reason before the generic
    # not-shared 404 (a roster campaign is never shared, but say why regardless).
    if db.is_roster(test_id):
        raise HTTPException(400, "this campaign's copies are pre-assigned by "
                            "roster; there is nothing to claim")
    if db.is_imported(test_id):
        raise HTTPException(400, "imported campaigns are investigation-only")
    if not db.is_shared(test_id):
        raise HTTPException(404, "no such campaign")
    if not db.is_assign_mode(test_id):
        raise HTTPException(400, "this campaign does not assign variants; "
                                 "pick any variant to print")
    try:
        m = store.load_manifest(test_id)
    except FileNotFoundError:
        raise HTTPException(404, "no such campaign")
    if m.get("status") != "generated":
        raise HTTPException(409, "test not generated")
    marked = [d for d in m.get("docs", []) if d["marked"]]
    doc_id = db.assign_variant(test_id, user["id"],
                               [d["doc_id"] for d in marked])
    if doc_id is None:
        raise HTTPException(409, "campaign is full")
    doc = next(d for d in marked if d["doc_id"] == doc_id)
    return {"doc_id": doc_id, "label": doc["label"],
            "n_pages": m["n_pages"]}


@app.get("/api/tests/{test_id}")
def get_test(test_id: str, user=Depends(require_user)):
    m = _manifest(test_id, user, allow_shared=True)
    scans = store.list_scans(test_id)
    assign_mode = db.is_assign_mode(test_id)
    m["assign_mode"] = assign_mode
    # Combined per-contributor reading: pool the caller's own real-photo
    # scans (across pages) and apply the single-scan attribution rule to
    # the totals. Always the requesting user's scans only, owner included.
    mine = db.user_scan_ids(test_id, user["id"])
    m["pooled_verdict"] = scan.pooled_verdict(
        [s for s in scans if s.get("scan_id") in mine
         and (s.get("source") or {}).get("kind") == "upload"])
    if not _is_owner(test_id, user):
        scans = [s for s in scans if s.get("scan_id") in mine]
        # Contributors must not see ground-truth material: a doc's seed
        # deterministically regenerates its codeword under the public
        # convention, and error tracebacks are owner-only.
        for d in m.get("docs", []):
            d.pop("seed", None)
        m.pop("error", None)
        if assign_mode:
            # Assigned campaigns: a contributor sees only their own variant
            # (nothing until they join).
            my = db.get_assignment(test_id, user["id"])
            m["my_assignment"] = my
            m["docs"] = [d for d in m.get("docs", [])
                         if d["doc_id"] == my]
    for s in scans:
        fb = db.get_feedback(s.get("scan_id", ""))
        if fb:
            s["feedback"] = {"judgment": fb["judgment"],
                             "true_doc_id": fb["true_doc_id"]}
    m["scans"] = scans
    m["shared"] = db.is_shared(test_id)
    m["is_owner"] = _is_owner(test_id, user)
    return m


@app.get("/api/tests/{test_id}/verify")
def verify(test_id: str, user=Depends(require_user)):
    m = _manifest(test_id, user, allow_shared=True)
    if m.get("status") != "generated":
        raise HTTPException(409, "test not generated")
    if m.get("type") in ("pdf_preserved", "pdf_raster", "pdf_vector"):
        # same file layout (docs/<id>/meta.json + document.pdf), same
        # commitment algo — one recompute serves all PDF carriers
        recomputed = render_pdf.recompute_commitment(m)
    else:
        recomputed = render.recompute_commitment(m)
    c = m["commitment"]
    # v2 manifests carry codebook_sha256; pre-v2 ones only sha256. Report the
    # seal version/kind so an investigator can tell WHAT was sealed: a codebook
    # seal proves which mark each copy carries, but says nothing about who
    # received which copy (that mapping is bound by the recovery key's keyed
    # commitment, not here).
    stored = c.get("codebook_sha256") or c["sha256"]
    return {"commitment_version": c.get("version", 1),
            "seal": c.get("seal", "codebook"),
            "stored": stored, "recomputed": recomputed,
            "match": recomputed == stored,
            "committed_utc": c["committed_utc"]}


# ---- recovery key (per-campaign export) --- owner/admin only (ground truth) ----
def _recovery_manifest(test_id, user):
    m = _manifest(test_id, user)            # allow_shared=False: not contributors
    if m.get("status") != "generated":
        raise HTTPException(409, "test not generated")
    return m


@app.get("/api/tests/{test_id}/recovery-info")
def recovery_info_route(test_id: str, user=Depends(require_user)):
    """Seal kind (plain language) + counts + digests for the export UI, without
    serving the ground-truth payload."""
    m = _recovery_manifest(test_id, user)
    try:
        return recovery.recovery_info(test_id, m)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RecoveryKeyReq(BaseModel):
    encrypt: bool = True
    passphrase: str | None = None
    acknowledge_passphrase_loss: bool = False
    acknowledge_plaintext: bool = False


@app.post("/api/tests/{test_id}/recovery-key")
def recovery_key_route(test_id: str, req: RecoveryKeyReq,
                       user=Depends(require_user), _=Depends(csrf_check)):
    """Download the self-contained recovery key (<test_id>.fdkey.json). POST
    (not GET) so the passphrase never rides in a URL. The acknowledgement
    fields are enforced gates, not UI decoration: an encrypted export requires
    acknowledging that a forgotten passphrase is unrecoverable; a plaintext
    export requires acknowledging the file is unencrypted."""
    m = _recovery_manifest(test_id, user)
    if req.encrypt:
        if not req.passphrase or len(req.passphrase) < recovery.MIN_PASSPHRASE:
            raise HTTPException(
                400, f"a passphrase of at least {recovery.MIN_PASSPHRASE} "
                "characters is required")
        if not req.acknowledge_passphrase_loss:
            raise HTTPException(400, "you must acknowledge that a forgotten "
                                "passphrase cannot be recovered")
        passphrase = req.passphrase
    else:
        if not req.acknowledge_plaintext:
            raise HTTPException(400, "you must acknowledge exporting an "
                                "unencrypted key")
        passphrase = None
    try:
        env = recovery.build_envelope(test_id, m, passphrase=passphrase)
    except ValueError as e:
        raise HTTPException(400, str(e))
    body = json.dumps(env, indent=1).encode("utf-8")
    return Response(content=body, media_type="application/json",
                    headers={"Content-Disposition":
                             f'attachment; filename="{test_id}.fdkey.json"'})


@app.get("/api/tests/{test_id}/receipt")
def receipt_route(test_id: str, user=Depends(require_user)):
    """Download the small commitment receipt (<test_id>-receipt.txt)."""
    m = _recovery_manifest(test_id, user)
    try:
        text = recovery.build_receipt(test_id, m)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=text.encode("utf-8"), media_type="text/plain",
                    headers={"Content-Disposition":
                             f'attachment; filename="{test_id}-receipt.txt"'})


MAX_KEY_MB = 64


@app.post("/api/import-recovery-key")
async def import_recovery_key(file: UploadFile = File(...),
                              passphrase: str = Form(""),
                              user=Depends(require_admin),
                              _=Depends(csrf_check)):
    """Import a recovery key onto this installation (admin). Integrity is fully
    verified before ANY write; the write is transactional; a divergent local
    campaign is never overwritten. Imported campaigns are investigation-only."""
    data = await read_limited(file, MAX_KEY_MB, "recovery key")
    try:
        env = json.loads(data.decode("utf-8"))
    except Exception:
        raise HTTPException(400, detail={"code": "damaged",
                            "message": "not a readable recovery key file"})
    try:
        payload = recovery.open_key(env, passphrase or None)
    except recovery.PassphraseRequired:
        raise HTTPException(422, detail={"code": "passphrase_required",
                            "message": "this recovery key is encrypted; enter "
                            "its passphrase"})
    except recovery.IncorrectPassphrase:
        raise HTTPException(422, detail={"code": "incorrect_passphrase",
                            "message": "incorrect passphrase"})
    except recovery.DamagedKey as e:
        raise HTTPException(400, detail={"code": "damaged", "message": str(e)})
    try:
        return recovery.import_key(env, payload, user["id"])
    except recovery.ImportConflict as e:
        raise HTTPException(409, detail={
            "code": "conflict",
            "message": "a different version of this campaign already exists "
                       "here; it will not be overwritten. Remove the local "
                       "campaign first if you intend to replace it.",
            "test_id": e.test_id,
            "local_codebook_sha256": e.local_codebook,
            "imported_codebook_sha256": e.imported_codebook})


def _name_recipient(test_id, result):
    """Resolve an attributed doc_id to the recipient it was issued to, so the
    verdict names a person -- not a 'Copy N'. Works for imported campaigns (from
    the recovery key's sealed mapping) and roster campaigns (from the roster
    fixed at creation). Join campaigns have no such sealed mapping here."""
    v = result.get("verdict") or {}
    if not (v.get("attributed") and v.get("doc_id")):
        return
    rec = None
    if db.is_imported(test_id):
        rec = db.imported_recipient(test_id, v["doc_id"])
    elif db.is_roster(test_id):
        rec = db.roster_recipient(test_id, v["doc_id"])
    if rec:
        v["recipient"] = rec["recipient"]


@app.get("/api/tests/{test_id}/pdf/{doc_id}")
def pdf(test_id: str, doc_id: str, user=Depends(require_user)):
    m = _manifest(test_id, user, allow_shared=True)
    if not store.valid_id(doc_id):
        raise HTTPException(404, "no such doc")
    doc = next((d for d in m.get("docs", []) if d["doc_id"] == doc_id), None)
    if not doc:
        raise HTTPException(404, "no such doc")
    # Assigned campaigns: contributors may only download their own variant
    if db.is_assign_mode(test_id) and not _is_owner(test_id, user) \
            and db.get_assignment(test_id, user["id"]) != doc_id:
        raise HTTPException(404, "no such doc")
    ddir = os.path.join(store.test_dir(test_id), "docs", doc_id)
    if m.get("type") in ("pdf_preserved", "pdf_raster", "pdf_vector"):
        return FileResponse(os.path.join(ddir, "document.pdf"),
                            media_type="application/pdf",
                            filename=f"{test_id}_{doc_id}.pdf")
    out = os.path.join(ddir, f"{doc_id}.pdf")
    if not os.path.exists(out):
        imgs = [Image.open(os.path.join(ddir, f"page{k}.png")).convert("L")
                for k in range(m["n_pages"])]
        imgs[0].save(out, save_all=True, append_images=imgs[1:],
                     resolution=300)
    return FileResponse(out, media_type="application/pdf",
                        filename=f"{test_id}_{doc_id}.pdf")


# Ownership-gated replacement for the old public /files mount. Images only:
# ground-truth metas (meta.json / page*_meta.json) are the answer key and
# are never servable.
_FILE_RE = re.compile(
    r"^(docs/[A-Za-z0-9-]+/page\d+(_thumb)?\.png"
    r"|scans/[A-Za-z0-9-]+/[A-Za-z0-9._-]*\.(?:jpg|jpeg|png))$")


@app.get("/api/files/{test_id}/{subpath:path}")
def files(test_id: str, subpath: str, user=Depends(require_user)):
    _manifest(test_id, user, allow_shared=True)
    if not _FILE_RE.match(subpath) or ".." in subpath:
        raise HTTPException(404, "no such file")
    if subpath.startswith("scans/") and not _is_owner(test_id, user):
        scan_id = subpath.split("/")[1]
        if scan_id not in db.user_scan_ids(test_id, user["id"]):
            raise HTTPException(404, "no such file")
    # Assigned campaigns: page images of variants other than the caller's
    # assignment stay hidden (a full-page PNG is the variant's geometry)
    if subpath.startswith("docs/") and not _is_owner(test_id, user) \
            and db.is_assign_mode(test_id):
        if db.get_assignment(test_id, user["id"]) != subpath.split("/")[1]:
            raise HTTPException(404, "no such file")
    p = os.path.join(store.test_dir(test_id), *subpath.split("/"))
    if not os.path.isfile(p):
        raise HTTPException(404, "no such file")
    return FileResponse(p)


def save_validated_photo(data, filename, sdir):
    """Persist an uploaded photo into sdir behind the image gates
    (decodable, pixel cap, resolution floor). Removes sdir and raises 400
    on failure; returns (img_path, ext)."""
    ext = os.path.splitext(filename or "input.jpg")[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    img_path = os.path.join(sdir, "input" + ext)
    with open(img_path, "wb") as f:
        f.write(data)
    try:                            # must be a decodable image
        with Image.open(img_path) as im:
            im.verify()
            w, h = im.size
    except Exception:
        shutil.rmtree(sdir, ignore_errors=True)
        raise HTTPException(400, "could not read that file as an image; "
                                 "upload the photo itself (JPG or PNG)")
    # Pixel cap BEFORE cv2 decodes in this process: a small JPEG under
    # Pillow's ~356 MP bomb threshold still inflates to a multi-GB buffer.
    if w * h > MAX_SCAN_PIXELS:
        shutil.rmtree(sdir, ignore_errors=True)
        raise HTTPException(400, "that photo is unusually large "
                                 f"({w}x{h}); phone photos are fine, "
                                 "but this demo caps images at "
                                 f"{MAX_SCAN_PIXELS // 1_000_000} megapixels")
    if max(w, h) < MIN_CAPTURE_PX:
        shutil.rmtree(sdir, ignore_errors=True)
        raise HTTPException(400, f"that photo is only {w}x{h} pixels — too "
                                 "small to carry the fine detail the hidden "
                                 "mark lives in. Please retake it closer "
                                 "and sharper (fill the frame with the "
                                 "page), or send the original photo file "
                                 "rather than a screenshot or thumbnail. "
                                 f"We need at least {MIN_CAPTURE_PX} px on "
                                 "the longest side")
    return img_path, ext


def _run_scan_slot(runner, m, img_path, source, pair):
    okslot, result = jobs.run_scan_slot(
        lambda: runner.run_scan(m, img_path, source, pair))
    if not okslot:
        raise HTTPException(429, "the decoder is busy with other scans; "
                                 "try again in a minute")
    return result


@app.post("/api/tests/{test_id}/scan")
async def scan_upload(test_id: str, request: Request,
                      file: UploadFile = File(...),
                      framing: str = Form("full"),
                      lighting: str = Form(""), note: str = Form(""),
                      printer: str = Form(""), phone: str = Form(""),
                      angle: str = Form(""),
                      user=Depends(require_user), _=Depends(csrf_check)):
    m = _manifest(test_id, user, allow_shared=True)
    if m.get("status") != "generated":
        raise HTTPException(409, "test not generated")
    rate_limit(user["id"], "upload", UPLOADS_PER_MIN)
    check_quota(user, "scan", QUOTA_SCANS_PER_DAY)
    data = await read_limited(file, MAX_PHOTO_MB, "photo")

    capture_meta = {}
    for key, val in (("printer", printer), ("phone", phone),
                     ("lighting", lighting), ("framing", framing),
                     ("angle", angle)):
        val = (val or "").strip()
        if val and val not in CAPTURE_ENUMS[key]:
            raise HTTPException(400, f"bad {key} value")
        capture_meta[key] = val or "unknown"

    scan_id, sdir = store.new_scan_dir(test_id)
    img_path, ext = save_validated_photo(data, file.filename, sdir)

    source = {"kind": "upload", "label": "real capture",
              "filename": file.filename, "note": note[:500],
              "synthetic": False, **capture_meta,
              "input_file": f"{test_id}/scans/{scan_id}/input{ext}"}
    runner = _runner_for(m)
    result = await run_in_threadpool(_run_scan_slot, runner, m, img_path,
                                     source, (scan_id, sdir))
    db.add_scan(scan_id, test_id, user["id"], "upload", result, capture_meta)
    db.add_event(user["id"], "scan")
    _name_recipient(test_id, result)
    return result


@app.post("/api/tests/{test_id}/simulate")
async def simulate(test_id: str, req: SimulateReq,
                   user=Depends(require_user), _=Depends(csrf_check)):
    m = _manifest(test_id, user)
    if m.get("status") != "generated":
        raise HTTPException(409, "test not generated")
    if db.is_imported(test_id):
        raise HTTPException(400, "imported campaigns have no source pages; "
                            "upload the leaked photo to /scan instead")
    doc = next((d for d in m["docs"] if d["doc_id"] == req.doc_id), None)
    if not doc:
        raise HTTPException(404, "no such doc")
    if not 0 <= req.page_index < m["n_pages"]:
        raise HTTPException(400, "bad page index")
    if req.preset not in channel_sim.PRESETS:
        raise HTTPException(400, f"preset must be one of "
                                 f"{sorted(channel_sim.PRESETS)}")
    check_quota(user, "scan", QUOTA_SCANS_PER_DAY)
    src = os.path.join(store.test_dir(test_id), "docs", req.doc_id,
                       f"page{req.page_index}.png")
    scan_id, sdir = store.new_scan_dir(test_id)
    img, cmds = channel_sim.simulate(src, sdir, req.preset)
    rel = os.path.relpath(img, store.TESTS_DIR).replace(os.sep, "/") \
        if img != src else f"{test_id}/docs/{req.doc_id}/page{req.page_index}.png"
    source = {"kind": "simulate", "label": "simulated channel",
              "sim_doc_id": req.doc_id, "sim_doc_label": doc["label"],
              "sim_marked": doc["marked"], "sim_page": req.page_index,
              "preset": req.preset, "channel_cmds": cmds, "synthetic": True,
              "input_file": rel}
    runner = _runner_for(m)
    result = await run_in_threadpool(_run_scan_slot, runner, m, img, source,
                                     (scan_id, sdir))
    db.add_scan(scan_id, test_id, user["id"], "simulate", result)
    db.add_event(user["id"], "scan")
    return result


@app.post("/api/tests/{test_id}/scans/{scan_id}/feedback")
def feedback(test_id: str, scan_id: str, req: FeedbackReq,
             user=Depends(require_user), _=Depends(csrf_check)):
    m = _manifest(test_id, user, allow_shared=True)
    if not store.valid_id(scan_id):
        raise HTTPException(404, "no such scan")
    row = db.get_scan(scan_id)
    if not row or row["test_id"] != test_id:
        raise HTTPException(404, "no such scan")
    if row["user_id"] != user["id"] and not auth.is_admin(user):
        raise HTTPException(404, "no such scan")   # only your own scans
    if row["kind"] != "upload":
        raise HTTPException(400, "feedback applies to real photo scans only")
    if req.judgment not in ("correct", "wrong", "unsure"):
        raise HTTPException(400, "judgment must be correct, wrong or unsure")
    valid_docs = {d["doc_id"] for d in m.get("docs", [])} | {"other"}
    if req.judgment == "wrong":
        if not req.true_doc_id:
            raise HTTPException(400, "when the machine was wrong, say which "
                                     "document you actually printed")
        if req.true_doc_id not in valid_docs:
            raise HTTPException(400, "unknown document")
    elif req.true_doc_id and req.true_doc_id not in valid_docs:
        raise HTTPException(400, "unknown document")
    true_doc = req.true_doc_id
    if req.judgment == "correct" and not true_doc:
        if not row["predicted_doc_id"]:
            raise HTTPException(400, "this scan made no prediction; say "
                                     "which document the photo shows")
        true_doc = row["predicted_doc_id"]     # confirmed prediction = truth
    db.set_feedback(scan_id, user["id"], req.judgment, true_doc,
                    req.note[:500] or None)
    fb = {"scan_id": scan_id, "judgment": req.judgment,
          "true_doc_id": true_doc, "note": req.note[:500],
          "created_utc": store.now_utc()}
    sdir = os.path.join(store.scans_dir(test_id), scan_id)
    if os.path.isdir(sdir):
        with open(os.path.join(sdir, "feedback.json"), "w",
                  encoding="utf-8") as f:
            json.dump(fb, f, indent=1)
    return {"ok": True, "feedback": fb}


# ---- volunteer pack flow ------------------------------------------------------
# No account: the pack code printed on the instruction sheet is the
# capability. Verdicts are withheld until every sheet has a readable
# capture so a volunteer can't learn mid-experiment which sheet is the
# control (engine/packs.py holds the state + report logic).
PACKS_ZIP_DIR = os.path.join(REPO, "demo", "packs")
PACK_UPLOADS_PER_MIN = int(os.environ.get("FF_PACK_UPLOADS_PER_MIN", 6))
PACK_READS_PER_MIN = int(os.environ.get("FF_PACK_READS_PER_MIN", 40))
PACK_MESSAGING = ("none", "whatsapp", "telegram", "other")


def _client_ip(request):
    """Caller IP for rate-limit buckets. Behind the shipped reverse proxy
    (uvicorn started with proxy_headers when FF_TRUST_PROXY is set) this is
    already the real client; request.client.host is the fallback."""
    return request.client.host if request.client else "unknown"


def _pack_status_payload(pid):
    state = packs.load_state(pid)
    done = packs.sheets_done(state)
    sheets = packs.sheet_letters(pid)
    revealed = set(done) >= set(sheets)
    return {"pack_id": pid, "sheets": sheets,
            "zip_url": f"/packs/pack_{pid}.zip",
            "sheets_done": done, "revealed": revealed,
            "report": packs.report(pid, state) if revealed else None}


@app.get("/api/packs/{pack_id}")
def pack_status(pack_id: str, request: Request):
    # Unauthenticated + a small code space of active packs: rate-limit per
    # IP so the code space cannot be cheaply enumerated.
    rate_limit(f"pack:{_client_ip(request)}", "pack-read", PACK_READS_PER_MIN)
    pid = (pack_id or "").strip().upper()
    if not packs.exists(pid):
        raise HTTPException(404, "no such pack")
    packs.ensure_test(pid)
    return _pack_status_payload(pid)


@app.post("/api/packs/{pack_id}/scan")
async def pack_scan(pack_id: str, request: Request,
                    file: UploadFile = File(...),
                    sheet: str = Form(...), messaging: str = Form("none"),
                    note: str = Form("")):
    pid = (pack_id or "").strip().upper()
    if not packs.exists(pid):
        raise HTTPException(404, "no such pack")
    rate_limit(f"pack:{_client_ip(request)}", "pack-upload",
               PACK_UPLOADS_PER_MIN)
    m = packs.ensure_test(pid)
    # Per-pack capture ceiling: an anonymous pack has no per-user quota, so
    # bound total stored photos to stop one code filling the disk.
    if packs.capture_count(packs.load_state(pid)) >= packs.MAX_CAPTURES:
        raise HTTPException(429, "this pack already has the maximum number "
                                 "of uploads; thank you — no more are needed")
    sheet = (sheet or "").strip().upper()
    if sheet not in packs.sheet_letters(pid):
        raise HTTPException(400, "say which sheet letter you photographed "
                                 "(A, B or C — it's printed on the sheet)")
    messaging = (messaging or "none").strip().lower() or "none"
    if messaging not in PACK_MESSAGING:
        raise HTTPException(400, "bad messaging value")
    data = await read_limited(file, MAX_PHOTO_MB, "photo")
    scan_id, sdir = store.new_scan_dir(m["test_id"])
    img_path, _ = save_validated_photo(data, file.filename, sdir)
    source = {"kind": "pack", "label": "volunteer pack capture",
              "pack_id": pid, "sheet": sheet, "messaging": messaging,
              "filename": file.filename, "note": note[:500],
              "synthetic": False}
    result = await run_in_threadpool(_run_scan_slot, scan, m, img_path,
                                     source, (scan_id, sdir))
    packs.record_capture(pid, sheet, scan_id, result, messaging, note)
    payload = _pack_status_payload(pid)
    payload.update({"recorded": True, "sheet": sheet,
                    "readable": bool(result.get("scores")),
                    "remaining": [s for s in payload["sheets"]
                                  if s not in payload["sheets_done"]]})
    if not result.get("scores"):
        payload["note"] = result.get("note") or (
            "the page could not be read from this photo; retake it flat, "
            "sharp and filling the frame — the sheet still counts once a "
            "readable photo arrives")
    return payload


@app.get("/packs/{fname}")
def pack_zip(fname: str, request: Request):
    rate_limit(f"pack:{_client_ip(request)}", "pack-read", PACK_READS_PER_MIN)
    if not re.fullmatch(r"pack_FP[0-9A-Z]{3,12}\.zip", fname):
        raise HTTPException(404, "no such pack")
    p = os.path.join(PACKS_ZIP_DIR, fname)
    if not os.path.isfile(p):
        raise HTTPException(404, "no such pack")
    return FileResponse(p, media_type="application/zip", filename=fname)


@app.get("/api/tests/{test_id}/funnel")
def funnel(test_id: str, user=Depends(require_user)):
    """Campaign funnel for the owner/admin: variants -> assigned ->
    uploaded -> feedback."""
    m = _manifest(test_id, user)        # owner or admin only (404 otherwise)
    n_variants = sum(1 for d in m.get("docs", []) if d["marked"])
    counts = db.funnel_counts(test_id)
    return {"n_variants": n_variants, **counts,
            "unassigned": max(n_variants - counts["assigned"], 0)}


@app.get("/api/tiers")
def tiers(user=Depends(require_user)):
    import metrics
    rows, _ = metrics.build_table()
    return {"rows": rows, "n": metrics.TABLE_N, "budget": metrics.TABLE_BUDGET}


# ---- admin --------------------------------------------------------------------
class ShareReq(BaseModel):
    shared: bool
    assigned: bool = False      # assigned-campaign mode: contributors join
                                # and are handed a specific variant


@app.post("/api/admin/tests/{test_id}/share")
def share_test(test_id: str, req: ShareReq, user=Depends(require_admin),
               _=Depends(csrf_check)):
    if not store.valid_id(test_id) or db.test_owner(test_id) is None:
        raise HTTPException(404, "no such test")
    if db.is_imported(test_id):
        raise HTTPException(400, "imported campaigns are investigation-only "
                            "and cannot be shared with contributors")
    if db.is_roster(test_id):
        raise HTTPException(400, "this is a roster campaign: every copy is "
                            "already assigned to a named recipient, so it "
                            "cannot be shared for contributors to join "
                            "(that would break its pre-distribution seal)")
    assign_mode = bool(req.shared and req.assigned)
    db.set_shared(test_id, req.shared, assign_mode)
    warning = None
    if req.shared:
        try:
            m = store.load_manifest(test_id)
            warning = campaign_capacity_warning(
                sum(1 for d in m.get("docs", []) if d["marked"]),
                m.get("n_pages"))
        except FileNotFoundError:
            pass
    return {"ok": True, "shared": req.shared, "assign_mode": assign_mode,
            "capacity_warning": warning}


@app.get("/api/admin/stats")
def admin_stats(user=Depends(require_admin)):
    return db.stats()


@app.get("/api/admin/contributions")
def admin_contributions(limit: int = 100, offset: int = 0,
                        user=Depends(require_admin)):
    return db.contributions(max(1, min(limit, 500)), max(offset, 0))


@app.get("/api/admin/export")
def admin_export(user=Depends(require_admin)):
    from engine import export
    path = export.build_export_zip()
    return FileResponse(path, media_type="application/zip",
                        filename=os.path.basename(path))


# ---- pages / static -----------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(HERE, "static", "admin.html"))


os.makedirs(store.TESTS_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")),
          name="static")


def _ttl_sweep():
    """Hourly: drop stale PDF uploads (24 h) and old export zips (7 d)."""
    targets = ((UPLOADS, 24 * 3600),
               (os.path.join(APPDATA, "exports"), 7 * 24 * 3600))
    while True:
        for d, ttl in targets:
            if not os.path.isdir(d):
                continue
            cutoff = time.time() - ttl
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                try:
                    if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                        os.remove(p)
                except OSError:
                    pass
        time.sleep(3600)


threading.Thread(target=_ttl_sweep, daemon=True).start()


@app.exception_handler(Exception)
async def unhandled(request, exc):
    log.error("unhandled error on %s %s", request.method, request.url.path,
              exc_info=exc)
    return JSONResponse(status_code=500,
                        content={"detail": "internal error"})


if __name__ == "__main__":
    # Local mode defaults to (and via the guard above, insists on) a
    # loopback bind; server mode keeps the same default and the operator
    # binds wider explicitly (the container sets HOST=0.0.0.0).
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8765))
    # Behind the shipped Caddy proxy the app port is NOT published (only
    # Caddy is), so trusting the proxy's X-Forwarded-For is safe and gives
    # per-client rate-limit buckets instead of one shared proxy-IP bucket.
    # Off by default for direct/local runs; set FF_TRUST_PROXY=1 in the
    # container. FF_FORWARDED_ALLOW_IPS overrides which upstreams to trust.
    trust_proxy = os.environ.get("FF_TRUST_PROXY") == "1"
    allow_ips = os.environ.get("FF_FORWARDED_ALLOW_IPS",
                               "*" if trust_proxy else "127.0.0.1")
    print(f"Fingerprint Desk ({MODE} mode) -> http://{host}:{port}")
    uv_config = uvicorn.Config(app, host=host, port=port,
                               log_level="warning",
                               proxy_headers=trust_proxy,
                               forwarded_allow_ips=allow_ips)
    GuardedServer(uv_config).run()
