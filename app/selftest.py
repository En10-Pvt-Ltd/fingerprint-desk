#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End-to-end self-test of the Fingerprint Desk app over the live API
surface (FastAPI TestClient, no server process needed).

    python app/selftest.py

Covers the research-pipeline checks (layout preview -> create/generate ->
commitment verify -> simulated leaks -> real-capture regression -> PDF
modes) plus the public-app layer: server-mode auth (first-run setup, local
email+password login with generic failures, bad-login rate limiting,
single-use invites), the local-mode loopback guard helper, CSRF, per-user
ownership, gated file serving (ground-truth metas never servable), the
5-variant cap, quotas, correct/wrong feedback, shared campaigns, assigned
campaigns (join/assignment isolation/funnel/capacity warning), and the
corpus export.

Runs the app in SERVER mode (FF_MODE=server): the first-run setup creates
the admin, and every further account is created through the invite flow --
exactly like a real deployment. Runs against a throwaway FF_APPDATA so
repeated runs never trip quotas or pollute real data. Repo fixtures
(received.jpeg, appdata/m1 corpus PDF) are read from the repo itself.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# ---- environment before any engine/serve import -------------------------------
WORKDIR = tempfile.mkdtemp(prefix="ff-selftest-")
os.environ["FF_APPDATA"] = os.path.join(WORKDIR, "appdata")
os.environ["FF_MODE"] = "server"
os.environ["ADMIN_EMAILS"] = "admin@selftest.local,admin2@selftest.local"
os.environ["FF_QUOTA_TESTS_PER_DAY"] = "2"
os.environ["FF_UPLOADS_PER_MIN"] = "100"
os.environ["FF_LOGINS_PER_MIN"] = "5"      # small so the cap is testable
os.environ["FF_PACK_MAX_CAPTURES"] = "3"   # small so the cap is testable
# No FF_FONT_PATH: exercise the shipped default (bundled Liberation Serif under
# assets/fonts/), so CI validates the exact font a fresh clone renders with.

from fastapi.testclient import TestClient   # noqa: E402
from serve import app, _assert_loopback     # noqa: E402
from engine import store, render, scan, db  # noqa: E402
import auth                                 # noqa: E402

PASS = 0
PASSWORD = "selftest-pass-123"


def ok(cond, label, detail=""):
    global PASS
    if not cond:
        print(f"  FAIL  {label}  {detail}")
        sys.exit(1)
    PASS += 1
    print(f"  ok    {label}{('  ' + detail) if detail else ''}")


def _fresh_client():
    return TestClient(app, raise_server_exceptions=True)


def _csrf(c):
    me = c.get("/api/me").json()
    c.headers["X-CSRF-Token"] = me["csrf"]
    return me


def login(email, password=PASSWORD):
    # Every TestClient shares one client IP, so drain the login rate-limit
    # buckets before each intentional login (the cap itself is exercised in
    # its own section below).
    auth._buckets.clear()
    c = _fresh_client()
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c, _csrf(c)


def make_user(admin_client, email, password=PASSWORD):
    """The server-mode way to create an account: admin invite + accept.
    Returns a logged-in client with the CSRF header set."""
    auth._buckets.clear()
    r = admin_client.post("/api/admin/invite", json={"email": email})
    assert r.status_code == 200, r.text
    token = r.json()["invite_path"].split("/")[-1]
    c = _fresh_client()
    r = c.post("/auth/accept-invite",
               json={"token": token, "password": password})
    assert r.status_code == 200, r.text
    return c, _csrf(c)


def wait_generated(c, tid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = c.get(f"/api/tests/{tid}").json()
        if m["status"] == "generated":
            return m
        if m["status"] == "error":
            sys.exit(f"generation error: {m.get('error')}\n{m.get('trace')}")
        time.sleep(0.5)
    sys.exit("generation timed out")


print("[0] server-mode first-run setup + auth gating")
anon = TestClient(app, raise_server_exceptions=True)
ok(anon.get("/api/tests").status_code == 401, "unauthenticated -> 401")
r = anon.get("/api/config")
ok(r.status_code == 200, "public config reachable")
cfg = r.json()
ok(cfg["mode"] == "server" and cfg["needs_setup"] is True,
   "fresh server reports mode=server, needs_setup", json.dumps(cfg))
ok("dev_login" not in cfg and "oauth_configured" not in cfg,
   "config no longer advertises dev-login/oauth")
ok(anon.post("/auth/dev-login",
             json={"email": "x@y.z"}).status_code in (404, 405),
   "dev-login shim is gone")
r = anon.post("/auth/setup", json={"email": "admin@selftest.local",
                                   "password": "short"})
ok(r.status_code == 400, "setup rejects a too-short password")
client = _fresh_client()
r = client.post("/auth/setup", json={"email": "admin@selftest.local",
                                     "password": PASSWORD})
ok(r.status_code == 200, "first-run setup creates the admin", r.text[:120])
me = _csrf(client)
ok(me["is_admin"], "setup account is admin")
ok(db.count_admins() == 1, "exactly one admin exists after setup")
r = _fresh_client().post("/auth/setup",
                         json={"email": "second@selftest.local",
                               "password": PASSWORD})
ok(r.status_code == 409, "second setup refused once an admin exists")
ok(anon.get("/api/config").json()["needs_setup"] is False,
   "needs_setup clears after setup")

print("[0b] login: success + generic failure")
client2, me2 = login("admin@selftest.local")
ok(me2["email"] == "admin@selftest.local" and me2["is_admin"],
   "email+password login works")
r = _fresh_client().post("/auth/login",
                         json={"email": "admin@selftest.local",
                               "password": "wrong-password-xx"})
ok(r.status_code == 401 and r.json()["detail"] == "invalid email or password",
   "wrong password -> generic 401")
r = _fresh_client().post("/auth/login",
                         json={"email": "ghost@selftest.local",
                               "password": PASSWORD})
ok(r.status_code == 401 and r.json()["detail"] == "invalid email or password",
   "unknown email -> the SAME generic 401 (no user enumeration)")
bad = _fresh_client()
bad.post("/auth/login", json={"email": "admin@selftest.local",
                              "password": PASSWORD})
r = bad.post("/api/layout", json={"content": "x y z"})
ok(r.status_code == 403, "POST without CSRF header -> 403")

print("[0c] bad-login rate limiting")
auth._buckets.clear()
rl = _fresh_client()
codes = [rl.post("/auth/login", json={"email": "rl@selftest.local",
                                      "password": "bad"}).status_code
         for _ in range(6)]
ok(codes[:5] == [401] * 5 and codes[5] == 429,
   "6th bad login inside a minute -> 429 (cap 5)", str(codes))
auth._buckets.clear()

print("[0d] invites: create -> accept -> non-admin account")
r = client.post("/api/admin/invite", json={"email": "invitee@selftest.local"})
ok(r.status_code == 200 and "/#/invite/" in r.json()["invite_path"],
   "admin mints an invite link", str(r.json())[:120])
inv_token = r.json()["invite_path"].split("/")[-1]
r = _fresh_client().post("/auth/accept-invite",
                         json={"token": "bogus-token", "password": PASSWORD})
ok(r.status_code == 400, "bogus invite token -> generic 400")
inv_c = _fresh_client()
r = inv_c.post("/auth/accept-invite",
               json={"token": inv_token, "password": PASSWORD})
ok(r.status_code == 200, "invite accepted, user signed in", r.text[:120])
ime = _csrf(inv_c)
ok(ime["email"] == "invitee@selftest.local" and not ime["is_admin"],
   "invited user is a non-admin")
r = _fresh_client().post("/auth/accept-invite",
                         json={"token": inv_token, "password": PASSWORD})
ok(r.status_code == 400, "invite is single-use")
ok(inv_c.get("/api/admin/stats").status_code == 403,
   "non-admin blocked from an admin route")
ok(inv_c.post("/api/admin/invite",
              json={"email": "x@y.z"}).status_code == 403,
   "non-admin cannot mint invites")
# Expired invite: backdate created_utc directly in the DB.
_admin_id = db.get_user_by_email("admin@selftest.local")["id"]
db.create_invite("expired-token-selftest", "late@selftest.local", _admin_id)
with db.conn() as _c:
    _c.execute("UPDATE invites SET created_utc=? WHERE token=?",
               ("2000-01-01T00:00:00+00:00", "expired-token-selftest"))
r = _fresh_client().post("/auth/accept-invite",
                         json={"token": "expired-token-selftest",
                               "password": PASSWORD})
ok(r.status_code == 400, "expired invite -> generic 400")
auth._buckets.clear()

print("[0e] local-mode loopback guard helper")


def _guard_exits(addrs, mode):
    try:
        _assert_loopback(addrs, mode)
        return False
    except SystemExit:
        return True


ok(_guard_exits(["0.0.0.0"], "local"), "0.0.0.0 in local mode is fatal")
ok(not _guard_exits(["127.0.0.1"], "local"), "127.0.0.1 passes")
ok(not _guard_exits(["::1"], "local"), "::1 passes")
ok(_guard_exits([], "local"), "empty socket list is fatal (ambiguity)")
ok(_guard_exits(["not-an-ip"], "local"), "unparsable address is fatal")
ok(_guard_exits(["127.0.0.1", "10.0.0.5"], "local"),
   "one non-loopback socket among loopbacks is fatal")
ok(not _guard_exits(["0.0.0.0"], "server"), "server mode is not guarded")

print("[0f] GuardedServer refuses at startup (the running server, not just "
      "the helper)")
import asyncio as _asyncio                                        # noqa: E402
import serve as _serve                                            # noqa: E402
from serve import GuardedServer                                   # noqa: E402
import uvicorn as _uvicorn                                        # noqa: E402


class _Sock:
    def __init__(self, name=None, raises=False):
        self._name, self._raises = name, raises

    def getsockname(self):
        if self._raises:
            raise OSError("simulated: socket cannot be inspected")
        return (self._name, 0)


class _Srv:
    def __init__(self, sockets):
        self.sockets = sockets


def _server_refuses(servers):
    """Drive the REAL guard on a controlled bound-socket set (local mode),
    no real socket opened. Returns True if the server refuses to serve."""
    saved = _serve.MODE
    _serve.MODE = "local"
    try:
        gs = GuardedServer(_uvicorn.Config(app))
        gs.servers = servers
        try:
            gs.assert_bound_loopback()
            return False
        except SystemExit:
            return True
    finally:
        _serve.MODE = saved


ok(_server_refuses([_Srv([_Sock(raises=True)])]),
   "getsockname() raising -> server refuses (cannot inspect sockets)")
ok(_server_refuses([]),
   "no inspectable socket -> server refuses (ambiguity)")
ok(_server_refuses([_Srv([_Sock("8.8.8.8")])]),
   "non-loopback bound socket -> server refuses")
ok(not _server_refuses([_Srv([_Sock("127.0.0.1")])]),
   "genuine loopback bind -> server serves")

print("[0g] commitment v2: keyed who-received-which mapping "
      "(reproducible + tamper-evident)")
from engine import commitment as _cm          # noqa: E402
import hashlib as _hl                          # noqa: E402
import json as _js                             # noqa: E402

# canonical_assignments: stable identity, sorted by doc_id, case/space
# normalised, and independent of the input order.
_shuf = [("v2", "  Bob@X.COM ", "t2"), ("v10", "c@x.com", "t3"),
         ("v1", "alice@x.com", "t1")]
_ca = _cm.canonical_assignments(_shuf)
ok([e["doc_id"] for e in _ca] == ["v1", "v10", "v2"],
   "canonical_assignments sorts by doc_id (fixed list order)")
ok(_ca[2]["recipient"] == "bob@x.com", "recipient normalised (trim + lowercase)")
ok(_cm.canonical_assignments(list(reversed(_shuf))) == _ca,
   "canonical_assignments is independent of input order")

# keyed_commitment: reproducible from the documented rule by an INDEPENDENT
# recompute (the third-party contract), and it binds both the mapping and seal.
_cb = "a" * 64
_k = _cm.keyed_commitment("mid-a", _cb, _ca, _cm.SEAL_SNAPSHOT)
_indep = _hl.sha256(_js.dumps(
    {"commitment_version": 2, "test_id": "mid-a", "codebook_sha256": _cb,
     "assignments": _ca, "mapping_seal": "snapshot"},
    sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
ok(_k == _indep, "keyed digest reproducible by an independent recompute")
ok(_cm.keyed_commitment("mid-a", _cb, _ca, _cm.SEAL_PREDISTRIBUTION) != _k,
   "seal kind is bound: snapshot digest != pre-distribution digest")
_tam = [dict(e) for e in _ca]
_tam[0]["recipient"] = "mallory@x.com"
ok(_cm.keyed_commitment("mid-a", _cb, _tam, _cm.SEAL_SNAPSHOT) != _k,
   "altering one recipient changes the keyed digest (tamper-evident)")
ok(_cm.keyed_commitment("mid-a", "b" * 64, _ca, _cm.SEAL_SNAPSHOT) != _k,
   "keyed digest binds the codebook anchor (different codebook -> different)")

# FROZEN normalisation: real email identities are byte-identical, so existing
# join-campaign digests are unchanged. This exact value is the pre-Phase-4
# anchor -- if this ever changes, every previously-sealed email mapping broke.
_pin = _cm.canonical_assignments([("v2", "  Bob@X.com ", "t2"),
                                  ("v1", "alice@x.com", "t1")])
ok(_cm.keyed_commitment("pin-campaign", "a" * 64, _pin, "snapshot")
   == "a895b556b546153c6111a71b856667abd1f0bb20d703ed02d78db9b6302b1e93",
   "email keyed digest unchanged by the frozen normalisation (join anchor)")
ok([e["recipient"] for e in _cm.canonical_assignments(
    [("v1", "  Centre   42 ", "t"), ("v2", "CENTRE 7", "t")])]
   == ["centre 42", "centre 7"],
   "label identity normalised: NFC + collapse whitespace + lowercase")
import unicodedata as _ud                     # noqa: E402
ok(_cm.normalize_recipient("Café")
   == _cm.normalize_recipient(_ud.normalize("NFD", "Café")),
   "NFC folds composed vs decomposed accents to one identity")

print("[1] layout preview")
r = client.post("/api/layout", json={"content": render.SAMPLE_TEXT})
ok(r.status_code == 200, "layout 200")
lay = r.json()
ok(lay["pages"] >= 2, "sample content paginates to 2+ pages",
   f"pages={lay['pages']} words={lay['words']}")
ok(lay["per_page"][0]["line_bits"] >= 10, "page 1 has line bits",
   str(lay["per_page"][0]))

print("[2] create + generate")
r = client.post("/api/tests", json={
    "name": "Selftest Paper", "content": render.SAMPLE_TEXT,
    "variant_labels": ["Variant 1", "Variant 2", "Variant 3"],
    "n_controls": 1, "sample_used": True})
ok(r.status_code == 200, "create 200", str(r.json()))
tid = r.json()["test_id"]
m = wait_generated(client, tid)
ok(len(m["docs"]) == 4, "4 docs generated")
ok(m["n_pages"] == lay["pages"], "page count matches preview")
for d in m["docs"]:
    for p in d["pages"]:
        png = os.path.join(store.test_dir(tid), "docs", d["doc_id"],
                           f"page{p['page_index']}.png")
        assert os.path.exists(png), png
ok(True, "all page PNGs + metas on disk")
ok(bool(m["commitment"]["sha256"]), "commitment sealed",
   m["commitment"]["sha256"][:16] + "...")
plain, _ = make_user(client, "plain-user@selftest.local")
r = plain.post("/api/tests", json={
    "name": "Too many", "content": render.SAMPLE_TEXT,
    "variant_labels": [f"V{i}" for i in range(6)], "n_controls": 1})
ok(r.status_code == 400, "6 variants -> 400 (non-admin cap is 5)")

print("[3] commitment verify")
v = client.get(f"/api/tests/{tid}/verify").json()
ok(v["match"], "recomputed commitment matches sealed digest")
ok(v["commitment_version"] == 2 and v["seal"] == "codebook",
   "verify reports v2 codebook seal",
   f"v={v['commitment_version']} seal={v['seal']}")
ok(m["commitment"]["codebook_sha256"] == m["commitment"]["sha256"],
   "v2 codebook_sha256 equals the deprecated sha256 alias (digest unchanged)")
# Backward compat: a pre-v2 manifest (only sha256, no version/seal) must still
# verify and be reported as version 1.
_leg = store.load_manifest(tid)
_leg["commitment"] = {"algo": _leg["commitment"]["algo"],
                      "sha256": _leg["commitment"]["sha256"],
                      "committed_utc": _leg["commitment"]["committed_utc"]}
store.save_manifest(_leg)
vleg = client.get(f"/api/tests/{tid}/verify").json()
ok(vleg["match"] and vleg["commitment_version"] == 1 and vleg["seal"] == "codebook",
   "legacy pre-v2 commitment still verifies, reported as version 1")
store.save_manifest(m)   # restore the v2 manifest

print("[4] simulated WhatsApp leak from Variant 2 (v2), page 1")
r = client.post(f"/api/tests/{tid}/simulate",
                json={"doc_id": "v2", "page_index": 0, "preset": "whatsapp"})
ok(r.status_code == 200, "simulate 200", str(r.json())[:200])
res = r.json()
ok(res["verdict"]["attributed"], "attributed", json.dumps(res["verdict"]))
ok(res["verdict"]["doc_id"] == "v2", "attributed to the true variant v2")
ok(res["verdict"]["acc"] >= 0.9, "agreement >= 0.9",
   f"acc={res['verdict']['acc']}")
runners = [s["acc"] for s in res["scores"] if s["doc_id"] != "v2"]
ok(all(a < 0.75 for a in runners), "runners-up near chance", str(runners))
ok(res["source"]["label"] == "simulated channel", "labeled simulated channel")

print("[5] simulated leak of the unmarked control (credibility check)")
r = client.post(f"/api/tests/{tid}/simulate",
                json={"doc_id": "ctrl1", "page_index": 0, "preset": "whatsapp"})
res = r.json()
ok(not res["verdict"]["attributed"], "control -> no attribution",
   json.dumps(res["verdict"]))
accs = [s["acc"] for s in res["scores"]]
ok(all(0.25 <= a <= 0.75 for a in accs), "all variants read near chance",
   str(accs))
r = client.post(f"/api/tests/{tid}/scans/{res['scan_id']}/feedback",
                json={"judgment": "correct"})
ok(r.status_code == 400, "feedback on a simulated scan -> 400")

print("[6] harsh preset behaves honestly (v3, page 2)")
r = client.post(f"/api/tests/{tid}/simulate",
                json={"doc_id": "v3", "page_index": m["n_pages"] - 1,
                      "preset": "harsh"})
res = r.json()
if res["verdict"]["attributed"]:
    ok(res["verdict"]["doc_id"] == "v3", "harsh: attributed correctly",
       f"acc={res['verdict']['acc']}")
else:
    ok(True, "harsh: honest no-attribution", json.dumps(res["verdict"]))
# page identification is layout/font dependent under the harsh preset: it
# must either name the right page or refuse with a plain-language note,
# never misidentify.
if res.get("page_index") is not None:
    ok(res["page_index"] == m["n_pages"] - 1, "page auto-identified",
       f"page_index={res['page_index']}")
else:
    ok(bool(res.get("note")), "harsh: honest unreadable-page note",
       str(res.get("note"))[:80])

print("[7] PDF export + gated files")
r = client.get(f"/api/tests/{tid}/pdf/v1")
ok(r.status_code == 200 and r.headers["content-type"] == "application/pdf"
   and len(r.content) > 10000, "variant PDF streams",
   f"{len(r.content)} bytes")
r = client.get(f"/api/files/{tid}/docs/v1/page0_thumb.png")
ok(r.status_code == 200, "owner can fetch page thumbnail")
r = client.get(f"/api/files/{tid}/docs/v1/page0_meta.json")
ok(r.status_code == 404, "ground-truth meta is never servable")
r = client.get(f"/api/files/{tid}/../../secrets")
ok(r.status_code in (404, 422), "path traversal rejected")

print("[8] ownership: another user sees nothing")
other, _ = make_user(client, "someone-else@selftest.local")
ok(other.get(f"/api/tests/{tid}").status_code == 404,
   "other user's GET test -> 404")
ok(other.get(f"/api/tests/{tid}/pdf/v1").status_code == 404,
   "other user's PDF download -> 404")
ok(other.get(f"/api/files/{tid}/docs/v1/page0_thumb.png").status_code == 404,
   "other user's file fetch -> 404")
ok(other.get("/api/tests").json() == [], "other user's test list is empty")
ok(other.get("/api/admin/stats").status_code == 403,
   "non-admin admin API -> 403")

print("[9] real-capture regression (repo dry-run print) + feedback")
dry_id = "dryrun-regression"
ddir = os.path.join(store.test_dir(dry_id), "docs", "v1")
os.makedirs(ddir, exist_ok=True)
meta = json.load(open(os.path.join(REPO, "meta.json")))
meta.update({"test_id": dry_id, "doc_id": "v1", "page_index": 0,
             "n_pages": 1, "marked": True})
json.dump(meta, open(os.path.join(ddir, "page0_meta.json"), "w"))
dry_manifest = {
    "test_id": dry_id, "name": "Dry-run regression", "status": "generated",
    "created_utc": store.now_utc(), "n_pages": 1,
    "docs": [{"doc_id": "v1", "label": "dry-run print", "seed": 42,
              "marked": True,
              "pages": [{"page_index": 0, "n_lines": meta["n_lines"]}]}]}
store.save_manifest(dry_manifest)
db.add_test(dry_id, db.get_user_by_email("admin@selftest.local")["id"],
            "rendered", 1, status="generated")

res = scan.run_scan(dry_manifest, os.path.join(REPO, "received.jpeg"),
                    {"kind": "upload", "label": "real capture",
                     "synthetic": False, "note": "phase A dry-run print"})
ok(res["path_used"] == "robust", "robust pipeline engaged")
best = res["scores"][0]
ok(best["line_ok"] == 14 and best["line_tot"] == 15,
   "real capture reads 14/15 line bits (0.933)", json.dumps(best))
ok(res["verdict"]["attributed"], "real capture attributed",
   f"p_adj={res['verdict']['p_adj']:.2e}")

res = scan.run_scan(dry_manifest,
                    os.path.join(REPO, "control_received.jpeg"),
                    {"kind": "upload", "label": "real capture",
                     "synthetic": False, "note": "phase A real control"})
ok(not res["verdict"]["attributed"], "real control -> no attribution",
   json.dumps(res["verdict"]))

# the same capture through the API: scan row, capture metadata, feedback
with open(os.path.join(REPO, "received.jpeg"), "rb") as f:
    r = client.post(f"/api/tests/{dry_id}/scan",
                    files={"file": ("leak.jpeg", f, "image/jpeg")},
                    data={"printer": "laser_mono", "phone": "flagship",
                          "lighting": "office", "note": "selftest"})
ok(r.status_code == 200, "API real-capture scan 200", r.text[:200])
api_scan = r.json()
ok(api_scan["verdict"]["attributed"]
   and api_scan["verdict"]["doc_id"] == "v1",
   "API real capture attributes v1")
sid = api_scan["scan_id"]
r = client.post(f"/api/tests/{dry_id}/scans/{sid}/feedback",
                json={"judgment": "wrong"})
ok(r.status_code == 400, "'wrong' without the true doc -> 400")
r = client.post(f"/api/tests/{dry_id}/scans/{sid}/feedback",
                json={"judgment": "correct"})
ok(r.status_code == 200, "feedback 'correct' accepted")
fb = db.get_feedback(sid)
ok(fb and fb["true_doc_id"] == "v1",
   "confirmed prediction recorded as ground truth")
ok(os.path.exists(os.path.join(store.scans_dir(dry_id), sid,
                               "feedback.json")),
   "feedback.json mirrored next to the scan")
# Ownership isolation extends to scans: another user can neither fetch the
# uploaded capture image nor touch its feedback.
ok(other.get(f"/api/files/{dry_id}/scans/{sid}/input.jpeg").status_code
   == 404, "other user's fetch of someone's scan image -> 404")
r = other.post(f"/api/tests/{dry_id}/scans/{sid}/feedback",
               json={"judgment": "correct"})
ok(r.status_code == 404, "other user's feedback on someone's scan -> 404")

print("[9b] margin rule, resolution gate, pooled per-contributor verdict")
# Margin rule: both wrong-variant cases from the 300-variant simulation
# (1-2 bit leads under extreme degradation) must abstain; a clean read
# (agreement ~0.94 vs runner-up ~0.55) must still attribute.
ok(scan.margin_check({"ok": 45, "tot": 51}, {"ok": 43, "tot": 51})[0] is False,
   "sim wrong-case 45/51 vs 43/51 fails the margin")
ok(scan.margin_check({"ok": 44, "tot": 52}, {"ok": 43, "tot": 52})[0] is False,
   "sim wrong-case 44/52 vs 43/52 fails the margin")
ok(scan.margin_check({"ok": 48, "tot": 51}, {"ok": 28, "tot": 51})[0] is True,
   "clean 0.94-vs-0.55 read passes the margin")
ok(scan.margin_check({"ok": 14, "tot": 15}, None)[0] is True,
   "single-variant test (no runner-up) passes trivially")
ok("margin" in api_scan["attribution_rule"],
   "scan results state the margin requirement",
   api_scan["attribution_rule"].get("margin", ""))

p_big = scan.binom_p(700, 1200)
ok(p_big is not None and 0.0 <= p_big <= 1.0,
   "binom_p is overflow-safe past 1023 bits", f"p={p_big:.3e}")

near = {"scores": [
    {"doc_id": "vA", "label": "Copy A", "ok": 45, "tot": 51},
    {"doc_id": "vB", "label": "Copy B", "ok": 43, "tot": 51}]}
pv = scan.pooled_verdict([near])
ok(pv is not None and not pv["attributed"]
   and "too closely" in (pv["abstain_reason"] or ""),
   "near-tie pools to abstention with plain-language reason",
   json.dumps(pv))
clean = {"scores": [
    {"doc_id": "vA", "label": "Copy A", "ok": 49, "tot": 51},
    {"doc_id": "vB", "label": "Copy B", "ok": 28, "tot": 51}]}
pv = scan.pooled_verdict([clean])
ok(pv["attributed"] and pv["attributed_doc"] == "vA"
   and pv["abstain_reason"] is None,
   "clean pooled read still attributes", json.dumps(pv))

# Pooled endpoint: a second real photo of the SAME page pools with the
# first without double-counting -- same-page photos re-observe the same
# physical bits, so only the best read of the page may contribute.
with open(os.path.join(REPO, "received.jpeg"), "rb") as f:
    r = client.post(f"/api/tests/{dry_id}/scan",
                    files={"file": ("leak2.jpeg", f, "image/jpeg")},
                    data={"note": "second photo for pooling"})
ok(r.status_code == 200, "second real capture scans", r.text[:120])
pv = client.get(f"/api/tests/{dry_id}").json().get("pooled_verdict")
ok(pv is not None and pv["n_photos"] >= 2,
   "pooled_verdict covers both photos", json.dumps(pv))
ok(pv["attributed"] and pv["attributed_doc"] == "v1"
   and pv["abstain_reason"] is None,
   "pooled verdict attributes v1", json.dumps(pv))
ok(pv["n_pages_used"] == 1
   and pv["n_bits"] == api_scan["verdict"]["tot"],
   "same-page photos don't double-count bits",
   f"pooled={pv['n_bits']} single={api_scan['verdict']['tot']}")

# Resolution gate: longest side under FF_MIN_CAPTURE_PX (default 1200) is
# rejected with retake guidance before any decoding; >= 1200 px passes.
import io                            # noqa: E402
from PIL import Image as PILImage    # noqa: E402
buf = io.BytesIO()
PILImage.new("L", (1000, 700), 255).save(buf, "JPEG")
r = client.post(f"/api/tests/{dry_id}/scan",
                files={"file": ("tiny.jpg", buf.getvalue(), "image/jpeg")})
ok(r.status_code == 400 and "1200" in r.json()["detail"],
   "1000px capture -> 400 with retake guidance", r.json()["detail"][:90])
with PILImage.open(os.path.join(REPO, "received.jpeg")) as src:
    sc = 1250 / max(src.size)
    small = src.convert("RGB").resize(
        (max(1, round(src.width * sc)), max(1, round(src.height * sc))))
buf = io.BytesIO()
small.save(buf, "JPEG", quality=88)
r = client.post(f"/api/tests/{dry_id}/scan",
                files={"file": ("small-ok.jpg", buf.getvalue(),
                                "image/jpeg")})
ok(r.status_code == 200, "1250px capture passes the gate", r.text[:120])

print("[10] PDF content source (Stage 1, isolated worker)")
import fitz  # noqa: E402
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 100), "alpha beta gamma delta epsilon zeta " * 4,
                 fontsize=11)
pdf_bytes = doc.tobytes()
doc.close()
r = client.post("/api/extract-pdf",
                files={"file": ("t.pdf", pdf_bytes, "application/pdf")})
ok(r.status_code == 200, "text PDF extracts", str(r.json())[:120])
ok("alpha beta gamma" in r.json()["content"], "extracted words present")
doc = fitz.open()
doc.new_page()
blank = doc.tobytes()
doc.close()
r = client.post("/api/extract-pdf",
                files={"file": ("b.pdf", blank, "application/pdf")})
ok(r.status_code == 400 and "scanned" in r.json()["detail"],
   "image-only/blank PDF rejected with guidance", r.json()["detail"][:80])
r = client.post("/api/extract-pdf",
                files={"file": ("junk.pdf", b"%PDF-not really a pdf",
                                "application/pdf")})
ok(r.status_code == 400, "corrupt PDF -> 400, server alive",
   r.json()["detail"][:60])

print("[11] formatting-preserved PDF test (Stage 2, isolated worker)")
pdfsrc = open(os.path.join(REPO, "appdata", "m1", "corpus",
                           "doc02_helv_headings.pdf"), "rb").read()
r = client.post("/api/analyze-pdf",
                files={"file": ("exam.pdf", pdfsrc, "application/pdf")})
ok(r.status_code == 200, "analyze-pdf 200", str({k: r.json()[k] for k in
   ("pages", "total_bits")}))
ana = r.json()
ok(ana["total_bits"] >= 10, "markable capacity found",
   f"total_bits={ana['total_bits']}")
r = client.post("/api/tests", json={
    "name": "Preserved PDF Selftest", "mode": "pdf_preserved",
    "upload_id": ana["upload_id"], "content": "",
    "variant_labels": ["Variant 1", "Variant 2"], "n_controls": 1})
ok(r.status_code == 200, "create preserved test 200", str(r.json()))
ptid = r.json()["test_id"]
pm = wait_generated(client, ptid)
ok(pm["type"] == "pdf_preserved", "manifest type pdf_preserved")
v1pdf = open(os.path.join(store.test_dir(ptid), "docs", "v1",
                          "document.pdf"), "rb").read()
ok(v1pdf != pdfsrc and len(v1pdf) > 1000,
   "variant PDF differs from source (marks embedded)")
ctlpdf = open(os.path.join(store.test_dir(ptid), "docs", "ctrl1",
                           "document.pdf"), "rb").read()
ok(ctlpdf == pdfsrc, "control PDF is a byte copy of the source")
v = client.get(f"/api/tests/{ptid}/verify").json()
ok(v["match"], "preserved commitment verifies (metas + pdf hashes)")
r = client.get(f"/api/tests/{ptid}/pdf/v1")
ok(r.status_code == 200 and r.content == v1pdf,
   "fingerprinted PDF download streams the embedded file")

r = client.post(f"/api/tests/{ptid}/simulate",
                json={"doc_id": "v2", "page_index": 0, "preset": "whatsapp"})
res = r.json()
ok(res["verdict"]["attributed"] and res["verdict"]["doc_id"] == "v2",
   "preserved: WhatsApp leak attributes true variant",
   json.dumps(res["verdict"]))
ok(res["scores"][0]["word_tot"] is None,
   "word cells reported absent, not erased")
r = client.post(f"/api/tests/{ptid}/simulate",
                json={"doc_id": "ctrl1", "page_index": 0,
                      "preset": "whatsapp"})
res = r.json()
ok(not res["verdict"]["attributed"],
   "preserved: control reads at chance, no attribution",
   json.dumps(res["verdict"]))

print("[11b] rich-content PDF (tables, drawings, pictures preserved)")
import io                                    # noqa: E402
import numpy as np                           # noqa: E402
from PIL import Image                        # noqa: E402
from engine import pdf_mark, pdf_scan, channel_sim   # noqa: E402

_para = ("The quick brown fox jumps over the lazy dog while the committee "
         "reviews the annual budget line by line and notes each variance.")
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_text((72, 70), "Quarterly Report", fontsize=16, fontname="hebo")
for i in range(9):
    page.insert_text((72, 110 + i * 16), f"{_para[:78]} (row {i + 1})",
                     fontsize=11, fontname="tiro")
tx, ty, cw, ch = 72, 280, 120, 24
table_rect = fitz.Rect(tx, ty, tx + 3 * cw, ty + 4 * ch)
for rr in range(5):
    page.draw_line((tx, ty + rr * ch), (tx + 3 * cw, ty + rr * ch), width=0.8)
for cc in range(4):
    page.draw_line((tx + cc * cw, ty), (tx + cc * cw, ty + 4 * ch), width=0.8)
for rr, rowtx in enumerate([["Region", "Units", "Revenue"],
                            ["North", "1,204", "$88,410"],
                            ["South", "977", "$71,120"],
                            ["West", "1,530", "$104,205"]]):
    for cc, txt in enumerate(rowtx):
        page.insert_text((tx + cc * cw + 6, ty + rr * ch + 16), txt,
                         fontsize=9, fontname="hebo" if rr == 0 else "tiro")
draw_rect = fitz.Rect(400, 400, 540, 500)
page.draw_circle((470, 430), 24, width=1.2)
page.draw_polyline([(405, 495), (440, 460), (475, 480), (535, 415)],
                   width=1.2)
grad = np.zeros((80, 160, 3), np.uint8)
grad[:, :, 0] = np.linspace(30, 220, 160, dtype=np.uint8)[None, :]
grad[:, :, 2] = np.linspace(220, 30, 80, dtype=np.uint8)[:, None]
_buf = io.BytesIO()
Image.fromarray(grad).save(_buf, "PNG")
img_rect = fitz.Rect(72, 400, 232, 480)
page.insert_image(img_rect, stream=_buf.getvalue())
for i in range(6):
    page.insert_text((72, 540 + i * 16), f"{_para[:78]} (closing {i + 1})",
                     fontsize=11, fontname="tiro")
rich_src = doc.tobytes()
doc.close()

cap11 = pdf_mark.capacity(rich_src)
ok(cap11["total_bits"] >= 4, "graphics page still carries line bits",
   f"total_bits={cap11['total_bits']}")
rich_pdf, rich_meta = pdf_mark.embed(rich_src, seed=1109)
ok(rich_meta["n_applied"] == rich_meta["n_slots"] > 0,
   "all planned slots applied",
   f"{rich_meta['n_applied']}/{rich_meta['n_slots']}")


def _r300(pdf_bytes):
    d = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = d[0].get_pixmap(dpi=300, colorspace=fitz.csGRAY)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    d.close()
    return arr


d11 = _r300(rich_src) != _r300(rich_pdf)
marked_ys = [ln["y_px300"] for pg11 in rich_meta["pages"]
             for bd in pg11["bands"] for ln in bd["lines"] if ln["applied"]]
stray = [int(r) for r in np.where(d11.any(axis=1))[0]
         if not any(-38 <= r - y <= 14 for y in marked_ys)]
ok(d11.sum() > 0 and not stray,
   "pixel changes confined to marked text lines",
   f"{int(d11.sum())} px on {len(marked_ys)} lines")
for nm, rect in (("table", table_rect), ("drawing", draw_rect),
                 ("image", img_rect)):
    sc11 = 300.0 / 72.0
    reg = d11[int(rect.y0 * sc11):int(rect.y1 * sc11) + 1,
              int(rect.x0 * sc11):int(rect.x1 * sc11) + 1]
    ok(int(reg.sum()) == 0, f"{nm} region pixel-identical")

wd11 = os.path.join(store.APPDATA, "selftest-rich")
os.makedirs(wd11, exist_ok=True)
png11 = os.path.join(wd11, "rich.png")
d = fitz.open(stream=rich_pdf, filetype="pdf")
d[0].get_pixmap(dpi=300).save(png11)
d.close()
cap_img, _ = channel_sim.simulate(png11, wd11, "whatsapp")
obs11 = pdf_scan.observe_page_robust(cap_img, rich_meta["pages"][0], wd11)
ok(obs11.get("ok"), "rich capture segments",
   str(obs11.get("path") or obs11.get("reason"))[:80])
ok11, tot11 = pdf_scan.score_page(obs11["bands"], rich_meta["pages"][0])
ok(tot11 == rich_meta["n_applied"] and ok11 == tot11,
   "rich page decodes through WhatsApp", f"{ok11}/{tot11}")
shutil.rmtree(wd11, ignore_errors=True)

print("[11c] scanned/image-only PDF (raster line-shift pathway)")
# Typeset a page, rasterize it, and re-import the bitmap as the page's
# sole content: an image-only PDF with zero text objects, like a scan.
doc = fitz.open()
page = doc.new_page(width=595, height=842)
for i in range(42):
    page.insert_text((60, 70 + i * 17), f"{_para[:70]} (scan row {i + 1})",
                     fontsize=9, fontname="tiro")
# Second, sparse page (few strips): a capture of page 1 must not be
# claimed by this page's degenerate 1-2 strip fit (page selection is by
# evidence, not accuracy — regression for the CBSE cover-page bug).
page2 = doc.new_page(width=595, height=842)
for i in range(9):
    page2.insert_text((60, 90 + i * 17), f"{_para[:60]} (annex {i + 1})",
                      fontsize=9, fontname="tiro")
pngs = [doc[k].get_pixmap(dpi=300, colorspace=fitz.csGRAY).tobytes("png")
        for k in range(2)]
doc.close()
doc = fitz.open()
for png in pngs:
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=png)
scan_src = doc.tobytes()
doc.close()

r = client.post("/api/extract-pdf",
                files={"file": ("scan.pdf", scan_src, "application/pdf")})
ok(r.status_code == 400 and "scanned" in r.json()["detail"],
   "text extraction still refuses an image-only PDF")
rc, _ = make_user(client, "raster-user@selftest.local")
r = rc.post("/api/analyze-pdf",
            files={"file": ("scan.pdf", scan_src, "application/pdf")})
ok(r.status_code == 200 and r.json().get("mode") == "pdf_raster",
   "analyze-pdf routes image-only PDF to the raster pathway",
   str(r.json())[:160])
rana = r.json()
ok(rana["total_bits"] >= 10, "enough markable strips for attribution",
   f"total_bits={rana['total_bits']}")
r = rc.post("/api/tests", json={
    "name": "Raster Selftest", "mode": "pdf_raster",
    "upload_id": rana["upload_id"], "content": "",
    "variant_labels": ["Copy A", "Copy B"], "n_controls": 1})
ok(r.status_code == 200, "create raster test 200", str(r.json()))
rtid = r.json()["test_id"]
rmani = wait_generated(rc, rtid)
ok(rmani["type"] == "pdf_raster", "manifest type pdf_raster")
rv1 = open(os.path.join(store.test_dir(rtid), "docs", "v1",
                        "document.pdf"), "rb").read()
rctl = open(os.path.join(store.test_dir(rtid), "docs", "ctrl1",
                         "document.pdf"), "rb").read()
ok(rv1 != scan_src and rctl == scan_src,
   "variant differs from source, control is a byte copy")
v = rc.get(f"/api/tests/{rtid}/verify").json()
ok(v["match"], "raster commitment verifies (metas + pdf hashes)")

r = rc.post(f"/api/tests/{rtid}/simulate",
            json={"doc_id": "v1", "page_index": 0, "preset": "whatsapp"})
res = r.json()
ok(res["verdict"]["attributed"] and res["verdict"]["doc_id"] == "v1",
   "raster: WhatsApp leak attributes true variant",
   json.dumps(res["verdict"]))
ok(res["scores"][0]["word_tot"] is None,
   "raster: word cells reported absent")
r = rc.post(f"/api/tests/{rtid}/simulate",
            json={"doc_id": "ctrl1", "page_index": 0, "preset": "whatsapp"})
res = r.json()
ok(not res["verdict"]["attributed"],
   "raster: control reads at chance, no attribution",
   json.dumps(res["verdict"]))

print("[11d] pdf worker failure interpretation (killed / error / garbled)")
# The parent must turn a silently-killed child (SIGSEGV from RLIMIT_AS on a
# large PDF leaves stdout AND stderr empty) into an actionable message, not
# an IndexError. Test the interpreter directly with synthetic child results.
from serve import _worker_result             # noqa: E402
from fastapi import HTTPException as _HX      # noqa: E402


def _wfail(rc, stdout, stderr, needle):
    try:
        _worker_result(rc, stdout, stderr)
    except _HX as e:
        return needle in e.detail
    return False


ok(_wfail(-11, "", "", "signal 11"),
   "killed worker (SIGSEGV, empty output) -> names the signal")
ok(_wfail(-11, "", "", "FF_PDF_WORKER_MEM_MB"),
   "killed-worker message points at the memory knob")
ok(_wfail(1, "", "Traceback\nboom: kaboom", "exited with an error"),
   "non-zero exit -> error message carrying the stderr tail")
ok(_wfail(0, "not json at all", "", "no readable result"),
   "exit 0 + garbled stdout -> unreadable-result message")
ok(_wfail(0, json.dumps({"ok": False, "error": "scanned/image-only"}), "",
          "scanned/image-only"),
   "worker-reported rejection surfaced verbatim")
ok(_worker_result(0, json.dumps({"ok": True, "test_id": "x"}), "")["test_id"]
   == "x", "ok result is returned to the caller")

# Marked docs must actually embed slots (zero-capacity guard, positive side).
from engine import raster_mark, render_raster, pdf_worker  # noqa: E402
rv1meta = json.load(open(os.path.join(store.test_dir(rtid), "docs", "v1",
                                      "meta.json"), encoding="utf-8"))
ok(rv1meta["n_slots"] > 0, "marked raster doc embeds slots",
   f"n_slots={rv1meta['n_slots']}")

# Crop retry must write its intermediate into the given workdir, never next
# to the committed page PNG (concurrent clean simulates raced on that path).
wd5 = os.path.join(WORKDIR, "crop-wd")
os.makedirs(wd5, exist_ok=True)
rv1_png = os.path.join(store.test_dir(rtid), "docs", "v1", "page0.png")
obs5 = raster_mark.observe(rv1_png, rv1meta["pages"][0], crop=True,
                           workdir=wd5)
ok(os.path.exists(os.path.join(wd5, "page0_crop.jpg")),
   "crop intermediate lands in the workdir")
ok(not os.path.exists(os.path.join(store.test_dir(rtid), "docs", "v1",
                                   "page0_crop.jpg")),
   "committed docs dir untouched by the crop retry")
ok(isinstance(obs5, dict) and "ok" in obs5,
   "observe with workdir returns a well-formed result")

# A vector page with a small decorative image (logo) must NOT be claimed
# by the raster carrier: its "single image" is not a page-covering scan.
doc = fitz.open()
page = doc.new_page(width=595, height=842)
for i in range(15):     # 15 text-line-like filled bars = vector paths
    page.draw_rect(fitz.Rect(60, 80 + i * 12, 520, 83 + i * 12),
                   color=None, fill=(0, 0, 0))
page.insert_image(fitz.Rect(500, 20, 560, 60), stream=_buf.getvalue())
logo_src = doc.tobytes()
doc.close()
try:
    raster_mark.analyze(logo_src, range(1))
    ok(False, "raster analyze must reject a decorative-image page")
except ValueError as e:
    ok("cover" in str(e), "raster analyze rejects non-covering page image",
       str(e))
route = pdf_worker._raster_fallback(logo_src, "no text objects")
ok(route.get("ok") and route.get("mode") == "pdf_vector",
   "worker routes logo-decorated vector page to pdf_vector",
   str(route)[:160])

# Zero-capacity guard: forcing the wrong carrier on a doc with no capacity
# must fail generation, not report a test of byte-identical "variants".
try:
    render_raster.generate_raster_test("Zero capacity", scan_src, ["X"], 1,
                                       "zerocap-selftest",
                                       carrier="pdf_vector")
    ok(False, "zero-capacity generation must raise")
except RuntimeError as e:
    ok("0 slots" in str(e), "zero-capacity generation raises RuntimeError",
       str(e)[:100])

# The analyze sidecar's detected mode is authoritative over the client's
# claimed mode: forcing pdf_vector on a detected-raster upload is ignored.
r = rc.post("/api/tests", json={
    "name": "Forced Mode", "mode": "pdf_vector",
    "upload_id": rana["upload_id"], "content": "",
    "variant_labels": ["Copy A"], "n_controls": 1})
ok(r.status_code == 200, "create with forced wrong mode accepted",
   str(r.json())[:120])
fm = wait_generated(rc, r.json()["test_id"])
ok(fm["type"] == "pdf_raster",
   "client-claimed mode overridden by the analyze sidecar's detected mode")

print("[12] quotas")
r = client.post("/api/tests", json={
    "name": "Over quota", "content": render.SAMPLE_TEXT,
    "variant_labels": ["Variant 1", "Variant 2"], "n_controls": 1})
ok(r.status_code == 429, "third test of the day -> 429 (quota 2)")

print("[13] shared campaign flow")
r = client.post(f"/api/admin/tests/{ptid}/share", json={"shared": True})
ok(r.status_code == 200, "admin shares the preserved test")
camps = other.get("/api/campaigns").json()
ok(any(c["test_id"] == ptid for c in camps),
   "campaign visible to other users")
r = other.get(f"/api/tests/{ptid}")
ok(r.status_code == 200, "other user can open the shared test")
ok(r.json()["scans"] == [], "other user sees no one else's scans")
ok(not r.json()["is_owner"], "shared test not owned by contributor")
r = other.get(f"/api/tests/{ptid}/pdf/v1")
ok(r.status_code == 200, "other user can download a shared variant PDF")
r = other.post(f"/api/tests/{ptid}/simulate",
               json={"doc_id": "v1", "page_index": 0, "preset": "clean"})
ok(r.status_code == 404, "contributor cannot run simulate on shared test")

print("[14] corpus export")
r = client.get("/api/admin/export")
ok(r.status_code == 200 and r.headers["content-type"] == "application/zip",
   "export zip streams")
zpath = os.path.join(WORKDIR, "export.zip")
open(zpath, "wb").write(r.content)
with zipfile.ZipFile(zpath) as z:
    names = z.namelist()
    caps = [n for n in names if n.startswith("export/captures/")
            and n.endswith(".json")]
    ok(len(caps) == 1, "one labeled capture exported", str(caps))
    side = json.loads(z.read(caps[0]))
    ok(side["synthetic"] is False and side["marked"] is True
       and side["variant"] == "v1" and side["judgment"] == "correct",
       "sidecar carries confirmed ground truth", json.dumps(side)[:160])
    img = caps[0][:-5]
    ok(img in names, "capture image present in zip")
    ok(f"export/docs/{dry_id}__v1_meta.json" in names,
       "ground-truth meta exported for the labeled doc")
# Raster/vector tests store one docs/<id>/meta.json; the export blob must
# find it (regression: only pdf_preserved hit the meta.json branch, so
# raster/vector captures exported with no ground truth at all).
from engine import export as _export                     # noqa: E402
_blob = _export._doc_meta_blob(rmani, "v1")
ok(_blob is not None and _blob.get("pages"),
   "raster test doc resolves its ground-truth meta blob for export")
_blob = _export._doc_meta_blob(pm, "v1")
ok(_blob is not None, "preserved test doc meta blob still resolves")
stats = client.get("/api/admin/stats").json()
ok(stats["feedback"].get("correct") == 1, "stats count the feedback",
   json.dumps(stats["feedback"]))

print("[15] assigned campaign")
# A second admin: created like any contributor (invite), then promoted via
# the db helper -- ADMIN_EMAILS no longer elevates once an admin exists.
admin2, _ = make_user(client, "admin2@selftest.local")
# Escalation regression: admin2's email is in ADMIN_EMAILS and an admin
# (admin@selftest.local) already exists. ADMIN_EMAILS must NOT be a live
# admin oracle -- admin2 stays a normal user until db.set_admin runs.
a2_pre = admin2.get("/api/me").json()
ok(not a2_pre["is_admin"],
   "ADMIN_EMAILS is not a live oracle: email in ADMIN_EMAILS is NOT admin "
   "while an admin already exists")
ok(admin2.get("/api/admin/stats").status_code == 403,
   "that same account is blocked (403) from an admin-only route")
db.set_admin(db.get_user_by_email("admin2@selftest.local")["id"])
a2 = admin2.get("/api/me").json()
ok(a2["is_admin"], "second admin (db.set_admin) recognized")
r = admin2.post("/api/tests", json={
    "name": "Assigned Campaign", "content": render.SAMPLE_TEXT,
    "variant_labels": ["Copy A", "Copy B", "Copy C"], "n_controls": 1})
ok(r.status_code == 200, "campaign create 200", str(r.json())[:120])
ok(r.json()["capacity_warning"] is None,
   "no capacity warning for 3 variants on a 2-page doc")
atid = r.json()["test_id"]
am = wait_generated(admin2, atid)
r = admin2.post(f"/api/admin/tests/{atid}/share",
                json={"shared": True, "assigned": True})
ok(r.status_code == 200 and r.json()["assign_mode"] is True,
   "shared in assigned mode", str(r.json())[:120])

from serve import campaign_capacity_warning  # noqa: E402
w = campaign_capacity_warning(300, 1)
ok(w is not None and "%" in w and "1-page" in w,
   "capacity warning fires for 300 variants x 1 page", w[:100])
ok(campaign_capacity_warning(5, 2) is None,
   "no capacity warning for a small test")
r = admin2.post("/api/tests", json={
    "name": "Too big campaign", "content": render.SAMPLE_TEXT,
    "variant_labels": [f"V{i}" for i in range(301)], "n_controls": 1})
ok(r.status_code == 400, "301 variants -> 400 (admin cap is 300)")

c1, _ = make_user(client, "contrib1@selftest.local")
c2, _ = make_user(client, "contrib2@selftest.local")
c3, _ = make_user(client, "contrib3@selftest.local")
c4, _ = make_user(client, "contrib4@selftest.local")
m0 = c1.get(f"/api/tests/{atid}").json()
ok(m0["assign_mode"] is True and m0["my_assignment"] is None
   and m0["docs"] == [], "pre-join manifest: assign_mode set, no docs")

r1 = c1.post(f"/api/campaigns/{atid}/join")
ok(r1.status_code == 200, "contributor 1 joins", r1.text[:120])
d1 = r1.json()["doc_id"]
ok(r1.json()["label"] and r1.json()["n_pages"] == am["n_pages"],
   "join returns doc_id/label/n_pages", str(r1.json()))
r1b = c1.post(f"/api/campaigns/{atid}/join")
ok(r1b.status_code == 200 and r1b.json()["doc_id"] == d1,
   "re-join is idempotent")
r2 = c2.post(f"/api/campaigns/{atid}/join")
d2 = r2.json()["doc_id"]
ok(r2.status_code == 200 and d2 != d1,
   "contributor 2 gets a different variant", f"{d1} vs {d2}")
r3 = c3.post(f"/api/campaigns/{atid}/join")
ok(r3.status_code == 200, "contributor 3 takes the last variant")
d3 = r3.json()["doc_id"]
ok({d1, d2, d3} == {"v1", "v2", "v3"},
   "marked variants assigned lowest-first, controls never assigned",
   str(sorted([d1, d2, d3])))
r4 = c4.post(f"/api/campaigns/{atid}/join")
ok(r4.status_code == 409 and "full" in r4.json()["detail"],
   "fourth join -> 409 campaign is full")

# assignment_rows -> the who-received-which mapping keyed by portable email
# (never the local user_id), the input to the recovery key's keyed commitment.
arows = db.assignment_rows(atid)
ok(len(arows) == 3 and all("user_id" not in r for r in arows)
   and {r["doc_id"] for r in arows} == {"v1", "v2", "v3"},
   "assignment_rows: 3 recipients, doc_ids only, no local user_id",
   str([(r["doc_id"], r["email"]) for r in arows]))
ok({r["email"] for r in arows} == {"contrib1@selftest.local",
   "contrib2@selftest.local", "contrib3@selftest.local"},
   "assignment_rows exposes recipient emails (portable identity)")
_acb = store.load_manifest(atid)["commitment"]["codebook_sha256"]
_aca = _cm.canonical_assignments([(r["doc_id"], r["email"], r["assigned_utc"])
                                  for r in arows])
_ak = _cm.keyed_commitment(atid, _acb, _aca, _cm.SEAL_SNAPSHOT)
ok(len(_ak) == 64 and _ak != _acb,
   "keyed commitment over the live mapping differs from the codebook digest")

print("[15b] recovery key export + commitment receipt")
ri = admin2.get(f"/api/tests/{atid}/recovery-info").json()
ok(ri["mapping_seal"] == "snapshot"
   and "predates distribution" in ri["seal_explain"],
   "recovery-info reports the snapshot seal in plain language")
ok(ri["n_recipients"] == 3 and ri["codebook_sha256"] == _acb,
   "recovery-info: 3 recipients, codebook digest matches the sealed one")
ok(c1.get(f"/api/tests/{atid}/recovery-info").status_code == 404,
   "recovery key is owner/admin only (a contributor gets 404)")

kr = admin2.post(f"/api/tests/{atid}/recovery-key",
                 json={"encrypt": False, "acknowledge_plaintext": True})
ok(kr.status_code == 200
   and "attachment" in kr.headers.get("content-disposition", ""),
   "recovery key downloads as an attachment")
env = kr.json()
ok(env["format"] == "fingerprint-desk-recovery-key" and env["version"] == 1,
   "envelope is versioned")
# payload_sha256 self-check (truncation/tamper), recomputed independently
_pay = _js.dumps(env["payload"], sort_keys=True, separators=(",", ":")).encode()
ok(_hl.sha256(_pay).hexdigest() == env["payload_sha256"],
   "payload_sha256 self-verifies (independent recompute)")
# the key reproduces the sealed codebook + keyed digests from its own contents
_kc = _cm.codebook_commitment(atid, env["payload"]["copies"], None)
ok(_kc == env["commitment"]["codebook_sha256"] == _acb,
   "key's own copies reproduce the sealed codebook digest")
_kk = _cm.keyed_commitment(atid, _kc, env["payload"]["assignments"], "snapshot")
ok(_kk == env["commitment"]["keyed_sha256"],
   "key reproduces the keyed (mapping) digest from its own contents")
ok(len(env["payload"]["assignments"]) == 3
   and all("email" not in a and "recipient" in a
           for a in env["payload"]["assignments"]),
   "key carries the canonical mapping (portable recipient identity, sorted)")
ok("document.pdf" not in _js.dumps(env) and "%PDF" not in _js.dumps(env),
   "recovery key contains no document bytes (re-trace, not re-issue)")

_rt = admin2.get(f"/api/tests/{atid}/receipt").text
ok("COMMITMENT RECEIPT" in _rt and "SNAPSHOT" in _rt
   and env["commitment"]["codebook_sha256"] in _rt
   and env["commitment"]["keyed_sha256"] in _rt,
   "receipt states what it is, the seal kind, and both digests")
ok(len(_rt) < 2500, "receipt fits on a page / in an email",
   f"{len(_rt)} chars")

print("[15c] recovery key encryption (Argon2id + AES-256-GCM)")
from engine import recovery as _rk         # noqa: E402
import copy as _copy                        # noqa: E402
PW = "correct horse battery staple"

# The acknowledgements are server-enforced gates, not just UI.
ok(admin2.post(f"/api/tests/{atid}/recovery-key",
   json={"encrypt": True, "passphrase": "short"}).status_code == 400,
   "encrypted export rejects a too-short passphrase")
ok(admin2.post(f"/api/tests/{atid}/recovery-key",
   json={"encrypt": True, "passphrase": PW,
         "acknowledge_passphrase_loss": False}).status_code == 400,
   "encrypted export refused without the passphrase-loss acknowledgement")
ok(admin2.post(f"/api/tests/{atid}/recovery-key",
   json={"encrypt": False, "acknowledge_plaintext": False}).status_code == 400,
   "plaintext export refused without the unencrypted acknowledgement")

kre = admin2.post(f"/api/tests/{atid}/recovery-key",
   json={"encrypt": True, "passphrase": PW,
         "acknowledge_passphrase_loss": True})
ok(kre.status_code == 200, "encrypted export succeeds with passphrase + ack")
enve = kre.json()
ok(enve["encryption"]["kdf"] == "argon2id"
   and enve["encryption"]["cipher"] == "AES-256-GCM"
   and isinstance(enve["payload"], str),
   "payload is encrypted; block names Argon2id + AES-256-GCM")
# header (identity + both digests) stays readable without the passphrase
ok(enve["campaign_id"] == atid
   and enve["commitment"]["codebook_sha256"] == env["commitment"]["codebook_sha256"]
   and enve["commitment"]["keyed_sha256"] == env["commitment"]["keyed_sha256"],
   "encrypted key's header + digests stay cleartext (escrowable)")
_a = enve["encryption"]["argon2"]
ok(all(k in _a for k in ("time_cost", "memory_cost", "parallelism",
                         "hash_len", "salt", "version")),
   "all Argon2id parameters travel in the file, not the code")

ok(_rk.open_key(enve, PW) == env["payload"],
   "encrypted round trip: open_key reproduces the exact payload")


def _err(fn):
    try:
        fn(); return "no-error"
    except Exception as e:
        return type(e).__name__


ok(_err(lambda: _rk.open_key(enve)) == "PassphraseRequired",
   "encrypted key with no passphrase -> PassphraseRequired")
ok(_err(lambda: _rk.open_key(enve, "wrong-passphrase")) == "IncorrectPassphrase",
   "wrong passphrase -> IncorrectPassphrase (not DamagedKey)")
_badh = _copy.deepcopy(enve)
_badh["commitment"]["codebook_sha256"] = "0" * 64
ok(_err(lambda: _rk.open_key(_badh, PW)) == "DamagedKey",
   "altered header digest -> DamagedKey (distinct from a passphrase error)")
_badp = _copy.deepcopy(env)
_badp["payload"]["assignments"][0]["recipient"] = "mallory@evil.test"
ok(_err(lambda: _rk.open_key(_badp)) == "DamagedKey",
   "tampered plaintext payload -> DamagedKey")
ok(_rk.open_key(env) == env["payload"],
   "plaintext key opens (backward compatible with pre-encryption keys)")

# parameters come from the FILE: opening still works after code defaults drift
_orig = _rk.ARGON2_DEFAULTS
_rk.ARGON2_DEFAULTS = {**_orig, "time_cost": _orig["time_cost"] + 7}
try:
    ok(_rk.open_key(enve, PW) == env["payload"],
       "open uses the file's KDF params, not the changed code defaults")
finally:
    _rk.ARGON2_DEFAULTS = _orig

m1_ = c1.get(f"/api/tests/{atid}").json()
ok(m1_["my_assignment"] == d1
   and [d["doc_id"] for d in m1_["docs"]] == [d1],
   "post-join manifest: only the assigned doc")
ok("seed" not in m1_["docs"][0], "assigned doc carries no seed")
ok(c1.get(f"/api/tests/{atid}/pdf/{d1}").status_code == 200,
   "assigned variant PDF downloads")
ok(c1.get(f"/api/tests/{atid}/pdf/{d2}").status_code == 404,
   "someone else's variant PDF -> 404")
ok(c1.get(f"/api/tests/{atid}/pdf/ctrl1").status_code == 404,
   "control PDF -> 404 for contributor")
ok(c1.get(f"/api/files/{atid}/docs/{d2}/page0_thumb.png").status_code == 404,
   "someone else's page image -> 404")
madm = admin2.get(f"/api/tests/{atid}").json()
ok(len(madm["docs"]) == 4 and "seed" in madm["docs"][0]
   and madm["assign_mode"] is True, "owner still sees all docs + seeds")
ok(admin2.get(f"/api/tests/{atid}/pdf/{d2}").status_code == 200,
   "owner downloads any variant")

f0 = admin2.get(f"/api/tests/{atid}/funnel").json()
ok(f0 == {"n_variants": 3, "assigned": 3, "contributors_uploaded": 0,
          "feedback_correct": 0, "feedback_wrong": 0, "unassigned": 0},
   "funnel after joins", json.dumps(f0))
ok(c1.get(f"/api/tests/{atid}/funnel").status_code == 404,
   "funnel is owner/admin only")

with open(os.path.join(REPO, "received.jpeg"), "rb") as f:
    r = c1.post(f"/api/tests/{atid}/scan",
                files={"file": ("leak.jpeg", f, "image/jpeg")},
                data={"note": "assigned-campaign upload"})
ok(r.status_code == 200, "assigned contributor uploads a photo",
   r.text[:160])
sid2 = r.json()["scan_id"]
r = c1.post(f"/api/tests/{atid}/scans/{sid2}/feedback",
            json={"judgment": "wrong", "true_doc_id": d1})
ok(r.status_code == 200, "contributor feedback recorded")
f1 = admin2.get(f"/api/tests/{atid}/funnel").json()
ok(f1["contributors_uploaded"] == 1 and f1["feedback_wrong"] == 1
   and f1["feedback_correct"] == 0, "funnel counts upload + feedback",
   json.dumps(f1))

print("[15d] recovery key import (transactional, conflict, investigation-only)")
import tempfile as _tf                       # noqa: E402
import shutil as _shutil                      # noqa: E402
from engine import channel_sim as _cs         # noqa: E402
IMP_PW = "import demo passphrase"

# A throwaway assigned campaign; a contributor joins so the key carries a
# who-received-which mapping, and we keep a synthetic leaked image of that copy
# OUTSIDE the campaign before deleting it (a machine that never saw it).
r = admin2.post("/api/tests", json={
    "name": "Import Demo", "content": render.SAMPLE_TEXT,
    "variant_labels": ["Alpha", "Beta"], "n_controls": 1, "sample_used": True})
itid = r.json()["test_id"]
wait_generated(admin2, itid)
admin2.post(f"/api/admin/tests/{itid}/share",
            json={"shared": True, "assigned": True})
leaker, _ = make_user(client, "leaker@school.example")
jdoc = leaker.post(f"/api/campaigns/{itid}/join").json()["doc_id"]
_leakdir = _tf.mkdtemp()
_leakimg, _ = _cs.simulate(
    os.path.join(store.test_dir(itid), "docs", jdoc, "page0.png"),
    _leakdir, "whatsapp")
_leakbytes = open(_leakimg, "rb").read()
ienv = admin2.post(f"/api/tests/{itid}/recovery-key", json={
    "encrypt": True, "passphrase": IMP_PW,
    "acknowledge_passphrase_loss": True}).json()
ipayload = _rk.open_key(ienv, IMP_PW)
_shutil.rmtree(store.test_dir(itid), ignore_errors=True)
with db.conn() as _c:
    _c.execute("DELETE FROM assignments WHERE test_id=?", (itid,))
    _c.execute("DELETE FROM tests WHERE test_id=?", (itid,))
ok(not os.path.exists(store.test_dir(itid)) and db.test_owner(itid) is None,
   "campaign removed -> simulates a machine that never saw it")
adminid = db.get_user_by_email("admin2@selftest.local")["id"]


def _snap():
    c = db.conn()
    return (sorted(os.listdir(store.TESTS_DIR)),
            c.execute("SELECT COUNT(*) n FROM tests").fetchone()["n"],
            c.execute("SELECT COUNT(*) n FROM imported_recipients")
            .fetchone()["n"])


# (1) integrity-first: a tampered key is refused and leaves ZERO trace
_snap0 = _snap()
_tam = _copy.deepcopy(ienv)
_tam["payload_sha256"] = "0" * 64
r = admin2.post("/api/import-recovery-key",
                files={"file": ("k.fdkey.json", _js.dumps(_tam),
                                "application/json")},
                data={"passphrase": IMP_PW})
ok(r.status_code == 400 and r.json()["detail"]["code"] == "damaged",
   "tampered key -> 400 damaged (integrity checked before any write)")
ok(_snap() == _snap0,
   "refused import left appdata + database byte-identical (zero trace)")

# (2) transactional: a failure DURING the write also leaves zero trace
_real_replace = os.replace
os.replace = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    _threw = _err(lambda: _rk.import_key(ienv, ipayload, adminid)) == "RuntimeError"
finally:
    os.replace = _real_replace
ok(_threw and _snap() == _snap0,
   "a failure mid-write rolls back fully (no dir, no orphaned rows)")

# (3) successful import (route), encrypted key + passphrase
r = admin2.post("/api/import-recovery-key",
                files={"file": ("k.fdkey.json", _js.dumps(ienv),
                                "application/json")},
                data={"passphrase": IMP_PW})
ok(r.status_code == 200 and r.json()["status"] == "imported"
   and r.json()["n_recipients"] == 1, "encrypted key imports", str(r.json()))
ok(os.path.exists(store.manifest_path(itid)) and db.is_imported(itid),
   "imported campaign on disk and flagged investigation-only")
ok(db.imported_recipient(itid, jdoc)["recipient"] == "leaker@school.example",
   "imported mapping resolves doc_id -> recipient email")

# (4) THE POINT: attribute a leak on the imported campaign -> NAME the recipient
r = admin2.post(f"/api/tests/{itid}/scan",
                files={"file": ("leak.jpg", _leakbytes, "image/jpeg")},
                data={"framing": "full"})
_v = r.json().get("verdict", {})
ok(_v.get("attributed") and _v.get("doc_id") == jdoc,
   "leak attributes to the leaked copy on the imported campaign", str(_v)[:100])
ok(_v.get("recipient") == "leaker@school.example",
   "verdict NAMES the recipient, not just a doc_id", str(_v.get("recipient")))

# (5) investigation-only: imported campaigns cannot be shared or simulated
ok(admin2.post(f"/api/admin/tests/{itid}/share",
   json={"shared": True}).status_code == 400,
   "imported campaign cannot be shared")
ok(admin2.post(f"/api/tests/{itid}/simulate",
   json={"doc_id": jdoc, "page_index": 0, "preset": "whatsapp"}).status_code
   == 400, "imported campaign cannot simulate (no source pages)")

# (6) conflict: same key = idempotent no-op; divergent codebook = hard refusal
r = admin2.post("/api/import-recovery-key",
                files={"file": ("k.fdkey.json", _js.dumps(ienv),
                                "application/json")},
                data={"passphrase": IMP_PW})
ok(r.status_code == 200 and r.json()["status"] == "already_present",
   "re-importing the same key is an idempotent no-op")
_snapC = _snap()
_div = _copy.deepcopy(ienv)
_div["commitment"]["codebook_sha256"] = "f" * 64
ok(_err(lambda: _rk.import_key(_div, ipayload, adminid)) == "ImportConflict",
   "divergent codebook -> ImportConflict (never silently merged)")
ok(_snap() == _snapC,
   "divergent-conflict refusal did not overwrite the local campaign")

print("[15e] roster campaign seals pre_distribution (Phase 4 foundation)")
# a fresh admin (admin2 has spent its per-day test quota)
radm, _ = make_user(client, "roster-admin@selftest.local")
db.set_admin(db.get_user_by_email("roster-admin@selftest.local")["id"])
r = radm.post("/api/tests", json={
    "name": "Roster Demo", "content": render.SAMPLE_TEXT,
    "variant_labels": ["Centre-1", "Centre-2"], "n_controls": 1,
    "sample_used": True})
rtid = r.json()["test_id"]
wait_generated(radm, rtid)
ok(_rk.current_seal(rtid, store.load_manifest(rtid)) == _cm.SEAL_SNAPSHOT,
   "a plain campaign still seals snapshot (join default unchanged)")
# fix a roster at creation, the way step-2's create flow will: count mode,
# label identities, normalised to exactly what gets sealed
db.record_roster(rtid, "count", "label",
                 [("v1", _cm.normalize_recipient(" Centre-1 "), None),
                  ("v2", _cm.normalize_recipient("CENTRE-2"),
                   "ops@centre2.example")])
ri = db.roster_info(rtid)
ok(db.is_roster(rtid) and ri["roster_mode"] == "count"
   and ri["identity_scheme"] == "label", "record_roster flags count/label")
ok(_rk.current_seal(rtid, store.load_manifest(rtid))
   == _cm.SEAL_PREDISTRIBUTION,
   "a roster campaign now seals PRE-DISTRIBUTION (machinery unchanged)")
rinfo = radm.get(f"/api/tests/{rtid}/recovery-info").json()
ok(rinfo["mapping_seal"] == "pre-distribution"
   and rinfo["identity_scheme"] == "label" and rinfo["roster_mode"] == "count",
   "recovery-info reports pre-distribution + count/label", str(rinfo)[:100])
renv = radm.post(f"/api/tests/{rtid}/recovery-key",
                   json={"encrypt": False, "acknowledge_plaintext": True}).json()
ok(renv["roster_mode"] == "count" and renv["identity_scheme"] == "label"
   and renv["commitment"]["mapping_seal"] == "pre-distribution",
   "key header carries roster_mode/identity_scheme + pre-distribution seal")
ok({a["recipient"] for a in renv["payload"]["assignments"]}
   == {"centre-1", "centre-2"},
   "sealed identities are the normalised roster labels")
ok(_cm.keyed_commitment(rtid, renv["commitment"]["codebook_sha256"],
   renv["payload"]["assignments"], "pre-distribution")
   == renv["commitment"]["keyed_sha256"],
   "keyed digest recomputes from the roster mapping + pre_distribution seal")
_rrt = radm.get(f"/api/tests/{rtid}/receipt").text
ok("PRE-DISTRIBUTION" in _rrt and "count-mode roster" in _rrt
   and "label->centre is external" in _rrt,
   "count-mode receipt states pre-distribution + the external label->centre caveat")

print("[16] volunteer pack flow (no account, verdicts withheld)")
# Fabricate pack FP001 in the throwaway appdata: v1 = the repo dry-run
# meta (received.jpeg is a real capture of it), v2 = every bit flipped
# (maximally distinct), ctrl = bits nulled. Letters deliberately shuffled.
import copy                                  # noqa: E402
pdir = os.path.join(os.environ["FF_APPDATA"], "volunteer_packs", "FP001",
                    "private")
os.makedirs(pdir, exist_ok=True)
v1m = json.load(open(os.path.join(REPO, "meta.json")))


def _flip(b):
    return None if b is None else 1 - b


v2m = copy.deepcopy(v1m)
ctlm = copy.deepcopy(v1m)
for ln2, lnc in zip(v2m["lines"], ctlm["lines"]):
    ln2["line_bit"] = _flip(ln2["line_bit"])
    ln2["word_bits"] = [_flip(b) for b in ln2["word_bits"]]
    lnc["line_bit"] = None
    lnc["word_bits"] = [None] * len(lnc["word_bits"])
json.dump(v1m, open(os.path.join(pdir, "v1_meta.json"), "w"))
json.dump(v2m, open(os.path.join(pdir, "v2_meta.json"), "w"))
json.dump(ctlm, open(os.path.join(pdir, "ctrl_meta.json"), "w"))
json.dump({"pack_id": "FP001", "mapping": {
    "A": {"role": "ctrl", "seed": 42, "unmarked": True},
    "B": {"role": "v1", "seed": 42, "unmarked": False},
    "C": {"role": "v2", "seed": 43, "unmarked": False}}},
    open(os.path.join(pdir, "mapping.json"), "w"))

packc = TestClient(app, raise_server_exceptions=True)   # anonymous: no login
ok(packc.get("/api/packs/FP999").status_code == 404, "unknown pack -> 404")
r = packc.get("/api/packs/fp001")
ok(r.status_code == 200, "pack status without any auth", r.text[:120])
ps = r.json()
ok(ps["sheets"] == ["A", "B", "C"] and ps["sheets_done"] == []
   and ps["revealed"] is False and ps["report"] is None,
   "fresh pack: three sheets, nothing revealed", json.dumps(ps))

with open(os.path.join(REPO, "received.jpeg"), "rb") as f:
    r = packc.post("/api/packs/FP001/scan",
                   files={"file": ("s.jpg", f, "image/jpeg")},
                   data={"sheet": "Z"})
ok(r.status_code == 400, "bad sheet letter -> 400")
with open(os.path.join(REPO, "received.jpeg"), "rb") as f:
    r = packc.post("/api/packs/FP001/scan",
                   files={"file": ("b.jpg", f, "image/jpeg")},
                   data={"sheet": "b", "messaging": "whatsapp"})
ok(r.status_code == 200, "sheet B capture accepted", r.text[:160])
pr = r.json()
ok(pr["recorded"] and pr["readable"] and pr["sheets_done"] == ["B"]
   and pr["remaining"] == ["A", "C"] and pr["revealed"] is False
   and pr["report"] is None,
   "verdict withheld after first sheet", json.dumps(
       {k: pr[k] for k in ("sheets_done", "remaining", "revealed")}))

with open(os.path.join(REPO, "control_received.jpeg"), "rb") as f:
    r = packc.post("/api/packs/FP001/scan",
                   files={"file": ("a.jpg", f, "image/jpeg")},
                   data={"sheet": "A"})
ok(r.status_code == 200 and r.json()["revealed"] is False,
   "still withheld after two of three sheets")

with open(os.path.join(REPO, "received.jpeg"), "rb") as f:
    r = packc.post("/api/packs/FP001/scan",
                   files={"file": ("c.jpg", f, "image/jpeg")},
                   data={"sheet": "C"})
ok(r.status_code == 200, "third sheet capture accepted", r.text[:160])
pr = r.json()
ok(pr["revealed"] is True and pr["report"] is not None,
   "all three sheets in -> report revealed")
rep = {row["sheet"]: row for row in pr["report"]}
ok(rep["B"]["outcome"] == "read-correct" and rep["B"]["marked"],
   "marked sheet read correctly", json.dumps(rep["B"]))
ok(rep["A"]["outcome"] == "control-passed" and not rep["A"]["marked"],
   "control sheet passed the false-accusation check", json.dumps(rep["A"]))
ok(rep["C"]["outcome"] == "read-wrong",
   "mislabeled sheet honestly reported as a wrong read",
   json.dumps(rep["C"]))
ok(packc.get("/api/packs/FP001").json()["report"] is not None,
   "report persists on later status reads")
r = packc.get("/packs/pack_FP001.zip")     # the repo ships this zip
ok(r.status_code == 200
   and r.headers["content-type"] == "application/zip",
   "pack zip streams", f"{len(r.content)} bytes")
ok(packc.get("/packs/pack_FP999.zip").status_code == 404,
   "absent zip -> 404")
ok(packc.get("/packs/../secrets.zip").status_code in (404, 422),
   "zip route rejects traversal")
# Per-pack capture cap (FF_PACK_MAX_CAPTURES=3 here): a 4th upload is
# refused so one anonymous code can't fill the disk.
from engine import packs as _packs                       # noqa: E402
ok(_packs.capture_count(_packs.load_state("FP001")) == 3,
   "three captures recorded")
with open(os.path.join(REPO, "received.jpeg"), "rb") as f:
    r = packc.post("/api/packs/FP001/scan",
                   files={"file": ("x.jpg", f, "image/jpeg")},
                   data={"sheet": "B"})
ok(r.status_code == 429 and "maximum" in r.json()["detail"],
   "capture cap -> 429", r.text[:100])
# Random codes new packs are minted with must validate and be long.
code = _packs.new_code()
ok(_packs.PACK_RE.match(code) and len(code) >= 10,
   "random pack code validates", code)

# pack_state durability: writes are atomic (temp file + os.replace, no
# stray .tmp) and a corrupt/torn state file degrades to empty state
# instead of poisoning every pack route forever.
sp16 = _packs._state_path("FP001")
ok(not os.path.exists(sp16 + ".tmp"),
   "no stray temp state file after captures")
with open(sp16, "w", encoding="utf-8") as f:
    f.write('{"captures": [tor')          # simulated torn write
ok(_packs.load_state("FP001") == {"captures": []},
   "corrupt pack_state tolerated as empty state")
st16 = _packs.record_capture("FP001", "B", "sc-recover", {}, "none", "")
ok(len(st16["captures"]) == 1
   and json.load(open(sp16, encoding="utf-8"))["captures"],
   "record_capture recovers from corrupt state and rewrites valid JSON")
ok(_packs.load_state("FPMISSING") == {"captures": []},
   "missing state file yields empty state")

shutil.rmtree(WORKDIR, ignore_errors=True)
print(f"\nALL {PASS} CHECKS PASSED")
