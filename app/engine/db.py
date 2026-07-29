# SPDX-License-Identifier: Apache-2.0
"""SQLite layer for the public app: users, ownership, feedback, quotas.

The file store under appdata/tests/ stays the source of truth for test
content (manifests, metas, images); rows here are an index over it plus the
relational data the file tree cannot answer (who owns what, feedback,
quota accounting). The DB is rebuildable from disk except for users and
feedback, so treat those tables as the crowdsourcing ground truth.
"""
import json
import os
import sqlite3
import threading

from . import APPDATA

DB_PATH = os.path.join(APPDATA, "app.db")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  google_sub TEXT UNIQUE NOT NULL,
  email TEXT NOT NULL,
  name TEXT,
  picture TEXT,
  created_utc TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  password_hash TEXT,
  auth_kind TEXT);
CREATE TABLE IF NOT EXISTS invites(
  token TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  used_utc TEXT,
  invited_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS tests(
  test_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  mode TEXT NOT NULL,
  n_variants INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS scans(
  scan_id TEXT PRIMARY KEY,
  test_id TEXT NOT NULL REFERENCES tests(test_id),
  user_id INTEGER NOT NULL,
  created_utc TEXT NOT NULL,
  kind TEXT NOT NULL,
  attributed INTEGER,
  predicted_doc_id TEXT,
  p_adj REAL,
  capture_meta TEXT);
CREATE TABLE IF NOT EXISTS feedback(
  scan_id TEXT PRIMARY KEY REFERENCES scans(scan_id),
  user_id INTEGER NOT NULL,
  judgment TEXT NOT NULL CHECK(judgment IN ('correct','wrong','unsure')),
  true_doc_id TEXT,
  note TEXT,
  created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  kind TEXT NOT NULL,
  created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignments(
  test_id TEXT NOT NULL REFERENCES tests(test_id),
  doc_id TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  assigned_utc TEXT NOT NULL,
  UNIQUE(test_id, doc_id),
  UNIQUE(test_id, user_id));
-- Recipient mapping for a campaign imported from a recovery key. Kept separate
-- from `assignments` because imported recipients are external identities (the
-- portable email carried in the key), not local user accounts.
CREATE TABLE IF NOT EXISTS imported_recipients(
  test_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  recipient TEXT NOT NULL,
  assigned_utc TEXT,
  PRIMARY KEY(test_id, doc_id));
CREATE INDEX IF NOT EXISTS idx_tests_user ON tests(user_id);
CREATE INDEX IF NOT EXISTS idx_scans_test ON scans(test_id);
CREATE INDEX IF NOT EXISTS idx_events ON events(user_id, kind, created_utc);
"""


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(APPDATA, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        _migrate(c)
        _local.conn = c
    return c


def _migrate(c):
    cols = {r["name"] for r in c.execute("PRAGMA table_info(tests)")}
    if "shared" not in cols:
        with c:
            c.execute("ALTER TABLE tests ADD COLUMN shared INTEGER"
                      " NOT NULL DEFAULT 0")
    if "assign_mode" not in cols:
        with c:
            c.execute("ALTER TABLE tests ADD COLUMN assign_mode INTEGER"
                      " NOT NULL DEFAULT 0")
    # Local-account auth (additive; older code simply ignores these).
    ucols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
    if "password_hash" not in ucols:
        with c:
            c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "auth_kind" not in ucols:
        with c:
            c.execute("ALTER TABLE users ADD COLUMN auth_kind TEXT")
    # Imported (recovery-key) campaigns are investigation-only.
    if "imported" not in cols:
        with c:
            c.execute("ALTER TABLE tests ADD COLUMN imported INTEGER"
                      " NOT NULL DEFAULT 0")


def _now():
    from . import store
    return store.now_utc()


# ---- users --------------------------------------------------------------------
# The google_sub column predates local accounts and is kept (schema is
# additive) but repurposed as a generic auth subject: password accounts use
# 'local:<email>', the local-mode operator uses 'implicit', and historical
# Google accounts keep their original Google sub.
def upsert_user(google_sub, email, name=None, picture=None):
    c = conn()
    with c:
        c.execute(
            "INSERT INTO users(google_sub, email, name, picture, created_utc)"
            " VALUES(?,?,?,?,?) ON CONFLICT(google_sub) DO UPDATE SET"
            " email=excluded.email, name=excluded.name,"
            " picture=excluded.picture",
            (google_sub, email, name, picture, _now()))
    return get_user_by_sub(google_sub)


def get_user(user_id):
    r = conn().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(r) if r else None


def get_user_by_sub(google_sub):
    r = conn().execute("SELECT * FROM users WHERE google_sub=?",
                       (google_sub,)).fetchone()
    return dict(r) if r else None


def get_user_by_email(email):
    r = conn().execute("SELECT * FROM users WHERE lower(email)=?",
                       ((email or "").strip().lower(),)).fetchone()
    return dict(r) if r else None


def create_local_user(email, password_hash, is_admin=0):
    """Password account (server mode); auth subject 'local:<email>'."""
    email = email.strip().lower()
    sub = "local:" + email
    with conn() as c:
        c.execute("INSERT INTO users(google_sub, email, created_utc,"
                  " is_admin, password_hash, auth_kind)"
                  " VALUES(?,?,?,?,?,'local')",
                  (sub, email, _now(), 1 if is_admin else 0, password_hash))
    return get_user_by_sub(sub)


def ensure_implicit_user():
    """Local mode's single operator account (subject 'implicit'), created
    on first need and always an admin."""
    u = get_user_by_sub("implicit")
    if u is None:
        with conn() as c:
            c.execute("INSERT OR IGNORE INTO users(google_sub, email, name,"
                      " created_utc, is_admin, auth_kind)"
                      " VALUES('implicit','operator@localhost',"
                      " 'Local operator',?,1,'implicit')", (_now(),))
        u = get_user_by_sub("implicit")
    if u and not u["is_admin"]:
        set_admin(u["id"])
        u = get_user(u["id"])
    return u


def set_password(user_id, password_hash):
    with conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?",
                  (password_hash, user_id))


def count_admins():
    r = conn().execute("SELECT COUNT(*) n FROM users"
                       " WHERE is_admin=1").fetchone()
    return r["n"]


def set_admin(user_id):
    with conn() as c:
        c.execute("UPDATE users SET is_admin=1 WHERE id=?", (user_id,))


def seed_admins_from_env(admin_emails):
    """Upgrade migration, run once at startup: ADMIN_EMAILS used to be a
    live admin oracle; it is now only a seed. Grant the persistent
    users.is_admin flag to every EXISTING user named in it, so active
    admins keep admin across the upgrade. New signups are never elevated
    by this (see auth._bootstrap_admin for the only other seed path)."""
    emails = {e.strip().lower() for e in (admin_emails or ())
              if e and e.strip()}
    if not emails:
        return 0
    n = 0
    c = conn()
    with c:
        for e in sorted(emails):
            n += c.execute("UPDATE users SET is_admin=1"
                           " WHERE lower(email)=? AND is_admin=0",
                           (e,)).rowcount
    return n


# ---- invites (server-mode local accounts) -------------------------------------
def create_invite(token, email, invited_by):
    with conn() as c:
        c.execute("INSERT INTO invites(token, email, created_utc,"
                  " invited_by) VALUES(?,?,?,?)",
                  (token, email, _now(), invited_by))


def get_invite(token):
    r = conn().execute("SELECT * FROM invites WHERE token=?",
                       (token,)).fetchone()
    return dict(r) if r else None


def consume_invite(token):
    """Mark the invite used; True only for the caller that actually
    consumed it (atomic single-use)."""
    with conn() as c:
        cur = c.execute("UPDATE invites SET used_utc=? WHERE token=?"
                        " AND used_utc IS NULL", (_now(), token))
        return cur.rowcount == 1


# ---- tests / ownership --------------------------------------------------------
def add_test(test_id, user_id, mode, n_variants, status="generating"):
    with conn() as c:
        c.execute("INSERT INTO tests(test_id, user_id, created_utc, status,"
                  " mode, n_variants) VALUES(?,?,?,?,?,?)",
                  (test_id, user_id, _now(), status, mode, n_variants))


def set_test_status(test_id, status):
    with conn() as c:
        c.execute("UPDATE tests SET status=? WHERE test_id=?",
                  (status, test_id))


def test_owner(test_id):
    r = conn().execute("SELECT user_id FROM tests WHERE test_id=?",
                       (test_id,)).fetchone()
    return r["user_id"] if r else None


def user_test_ids(user_id):
    rows = conn().execute(
        "SELECT test_id FROM tests WHERE user_id=? ORDER BY created_utc DESC",
        (user_id,)).fetchall()
    return [r["test_id"] for r in rows]


def is_shared(test_id):
    r = conn().execute("SELECT shared FROM tests WHERE test_id=?",
                       (test_id,)).fetchone()
    return bool(r and r["shared"])


def set_shared(test_id, shared, assign_mode=False):
    with conn() as c:
        c.execute("UPDATE tests SET shared=?, assign_mode=? WHERE test_id=?",
                  (1 if shared else 0, 1 if assign_mode else 0, test_id))


def is_assign_mode(test_id):
    r = conn().execute("SELECT assign_mode FROM tests WHERE test_id=?",
                       (test_id,)).fetchone()
    return bool(r and r["assign_mode"])


def campaign_test_ids():
    """Shared, fully generated tests every signed-in contributor may use."""
    rows = conn().execute(
        "SELECT test_id FROM tests WHERE shared=1 AND status='generated'"
        " ORDER BY created_utc DESC").fetchall()
    return [r["test_id"] for r in rows]


def user_scan_ids(test_id, user_id):
    rows = conn().execute(
        "SELECT scan_id FROM scans WHERE test_id=? AND user_id=?",
        (test_id, user_id)).fetchall()
    return {r["scan_id"] for r in rows}


# ---- assignments (assigned-campaign mode) -------------------------------------
def get_assignment(test_id, user_id):
    """The doc_id assigned to this user in this test, or None."""
    r = conn().execute(
        "SELECT doc_id FROM assignments WHERE test_id=? AND user_id=?",
        (test_id, user_id)).fetchone()
    return r["doc_id"] if r else None


def assign_variant(test_id, user_id, candidate_doc_ids):
    """Assign the first free doc among candidate_doc_ids (in order) to the
    user. Idempotent: an existing assignment is returned as-is. Concurrent
    joins are made safe by the UNIQUE(test_id, doc_id) / (test_id, user_id)
    constraints: on IntegrityError we re-read and retry with the fresher
    taken-set. Returns the doc_id, or None when every candidate is taken."""
    c = conn()
    existing = get_assignment(test_id, user_id)
    if existing:
        return existing
    for _ in range(len(candidate_doc_ids) + 1):
        taken = {r["doc_id"] for r in c.execute(
            "SELECT doc_id FROM assignments WHERE test_id=?", (test_id,))}
        free = [d for d in candidate_doc_ids if d not in taken]
        if not free:
            return None
        try:
            with c:
                c.execute("INSERT INTO assignments(test_id, doc_id, user_id,"
                          " assigned_utc) VALUES(?,?,?,?)",
                          (test_id, free[0], user_id, _now()))
            return free[0]
        except sqlite3.IntegrityError:
            existing = get_assignment(test_id, user_id)
            if existing:            # lost a race against ourselves elsewhere
                return existing     # (double-click): keep the first one
            continue                # doc got taken; retry with fresh state
    return None


def count_assignments(test_id):
    r = conn().execute("SELECT COUNT(*) n FROM assignments WHERE test_id=?",
                       (test_id,)).fetchone()
    return r["n"]


def is_imported(test_id):
    """True if this campaign was imported from a recovery key (investigation-
    only: it can be scanned/attributed but never generates new copies)."""
    r = conn().execute("SELECT imported FROM tests WHERE test_id=?",
                       (test_id,)).fetchone()
    return bool(r and r["imported"])


def imported_recipient(test_id, doc_id):
    """The recipient (portable identity) a doc_id was assigned to in an
    imported campaign, from the recovery key's sealed mapping, or None."""
    r = conn().execute("SELECT recipient, assigned_utc FROM imported_recipients"
                       " WHERE test_id=? AND doc_id=?",
                       (test_id, doc_id)).fetchone()
    return dict(r) if r else None


def assignment_rows(test_id):
    """The who-received-which mapping joined to each recipient's STABLE identity
    (email + display name), ordered by doc_id. For the recovery key and its
    keyed commitment. The local users.id is deliberately omitted: it is
    installation-specific and would make an off-box digest unreproducible; the
    email is the portable identity a third party can check."""
    rows = conn().execute(
        "SELECT a.doc_id, u.email, u.name, a.assigned_utc"
        " FROM assignments a JOIN users u ON u.id = a.user_id"
        " WHERE a.test_id=? ORDER BY a.doc_id", (test_id,)).fetchall()
    return [dict(r) for r in rows]


def funnel_counts(test_id):
    """Campaign funnel over assigned contributors: how many joined, how many
    of those uploaded at least one real photo, and how their feedback split."""
    c = conn()
    up = c.execute(
        "SELECT COUNT(DISTINCT a.user_id) n FROM assignments a"
        " JOIN scans s ON s.test_id=a.test_id AND s.user_id=a.user_id"
        " WHERE a.test_id=? AND s.kind='upload'", (test_id,)).fetchone()["n"]
    fb = {r["judgment"]: r["n"] for r in c.execute(
        "SELECT f.judgment, COUNT(*) n FROM assignments a"
        " JOIN scans s ON s.test_id=a.test_id AND s.user_id=a.user_id"
        " JOIN feedback f ON f.scan_id=s.scan_id"
        " WHERE a.test_id=? AND s.kind='upload' GROUP BY f.judgment",
        (test_id,))}
    return {"assigned": count_assignments(test_id),
            "contributors_uploaded": up,
            "feedback_correct": fb.get("correct", 0),
            "feedback_wrong": fb.get("wrong", 0)}


# ---- scans / feedback ---------------------------------------------------------
def add_scan(scan_id, test_id, user_id, kind, result, capture_meta=None):
    v = result.get("verdict") or {}
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO scans(scan_id, test_id, user_id,"
                  " created_utc, kind, attributed, predicted_doc_id, p_adj,"
                  " capture_meta) VALUES(?,?,?,?,?,?,?,?,?)",
                  (scan_id, test_id, user_id, _now(), kind,
                   int(bool(v.get("attributed"))), v.get("doc_id"),
                   v.get("p_adj"),
                   json.dumps(capture_meta) if capture_meta else None))


def get_scan(scan_id):
    r = conn().execute("SELECT * FROM scans WHERE scan_id=?",
                       (scan_id,)).fetchone()
    return dict(r) if r else None


def set_feedback(scan_id, user_id, judgment, true_doc_id=None, note=None):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO feedback(scan_id, user_id,"
                  " judgment, true_doc_id, note, created_utc)"
                  " VALUES(?,?,?,?,?,?)",
                  (scan_id, user_id, judgment, true_doc_id, note, _now()))


def get_feedback(scan_id):
    r = conn().execute("SELECT * FROM feedback WHERE scan_id=?",
                       (scan_id,)).fetchone()
    return dict(r) if r else None


# ---- quotas -------------------------------------------------------------------
def add_event(user_id, kind):
    with conn() as c:
        c.execute("INSERT INTO events(user_id, kind, created_utc)"
                  " VALUES(?,?,?)", (user_id, kind, _now()))


def count_events(user_id, kind, since_utc):
    r = conn().execute(
        "SELECT COUNT(*) AS n FROM events WHERE user_id=? AND kind=?"
        " AND created_utc >= ?", (user_id, kind, since_utc)).fetchone()
    return r["n"]


# ---- admin --------------------------------------------------------------------
def stats():
    c = conn()
    one = lambda q, *a: c.execute(q, a).fetchone()  # noqa: E731
    out = {
        "users": one("SELECT COUNT(*) n FROM users")["n"],
        "tests": one("SELECT COUNT(*) n FROM tests")["n"],
        "scans_real": one("SELECT COUNT(*) n FROM scans"
                          " WHERE kind='upload'")["n"],
        "scans_simulated": one("SELECT COUNT(*) n FROM scans"
                               " WHERE kind='simulate'")["n"],
        "scans_attributed": one("SELECT COUNT(*) n FROM scans"
                                " WHERE kind='upload' AND attributed=1")["n"],
        "feedback": {r["judgment"]: r["n"] for r in c.execute(
            "SELECT judgment, COUNT(*) n FROM feedback GROUP BY judgment")},
    }
    out["confusion"] = [dict(r) for r in c.execute(
        "SELECT s.predicted_doc_id, f.judgment, f.true_doc_id, COUNT(*) n"
        " FROM feedback f JOIN scans s ON s.scan_id=f.scan_id"
        " WHERE s.kind='upload'"
        " GROUP BY s.predicted_doc_id, f.judgment, f.true_doc_id")]
    return out


def contributions(limit=100, offset=0):
    rows = conn().execute(
        "SELECT s.*, f.judgment, f.true_doc_id, f.note AS feedback_note,"
        " u.email FROM scans s"
        " LEFT JOIN feedback f ON f.scan_id=s.scan_id"
        " JOIN users u ON u.id=s.user_id"
        " WHERE s.kind='upload'"
        " ORDER BY s.created_utc DESC LIMIT ? OFFSET ?",
        (limit, offset)).fetchall()
    return [dict(r) for r in rows]


def labeled_uploads():
    """Real captures with definite ground truth for the corpus export:
    judgment 'correct' (truth = predicted doc) or 'wrong' with an asserted
    true_doc_id that names a doc (not 'other')."""
    rows = conn().execute(
        "SELECT s.*, f.judgment, f.true_doc_id FROM scans s"
        " JOIN feedback f ON f.scan_id=s.scan_id"
        " WHERE s.kind='upload' AND (f.judgment='correct'"
        "  OR (f.judgment='wrong' AND f.true_doc_id IS NOT NULL"
        "      AND f.true_doc_id != 'other'))").fetchall()
    return [dict(r) for r in rows]
