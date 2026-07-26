# SPDX-License-Identifier: Apache-2.0
"""File-based store for tests and scans under appdata/tests/<test_id>/.

Everything is plain files (PNG, JSON) mirroring the research repo's corpus
conventions, so a generated test can be inspected, printed, or fed back into
the research harness by hand.
"""
import datetime
import json
import os
import re
import secrets

from . import APPDATA

TESTS_DIR = os.path.join(APPDATA, "tests")

# test_id/doc_id/scan_id path components: slug chars only, no separators,
# so a route param can never traverse out of TESTS_DIR.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,79}$")


def valid_id(s):
    return bool(s) and bool(_ID_RE.match(s))


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "test"


def new_test_id(name):
    return f"{slugify(name)}-{secrets.token_hex(2)}"


def test_dir(test_id):
    return os.path.join(TESTS_DIR, test_id)


def manifest_path(test_id):
    return os.path.join(test_dir(test_id), "manifest.json")


def save_manifest(m):
    os.makedirs(test_dir(m["test_id"]), exist_ok=True)
    with open(manifest_path(m["test_id"]), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)


def load_manifest(test_id):
    with open(manifest_path(test_id), encoding="utf-8") as f:
        return json.load(f)


def list_tests():
    if not os.path.isdir(TESTS_DIR):
        return []
    out = []
    for tid in sorted(os.listdir(TESTS_DIR)):
        p = manifest_path(tid)
        if os.path.exists(p):
            m = json.load(open(p, encoding="utf-8"))
            m["n_scans"] = len(list_scans(tid))
            out.append(m)
    out.sort(key=lambda m: m.get("created_utc", ""), reverse=True)
    return out


def scans_dir(test_id):
    return os.path.join(test_dir(test_id), "scans")


def new_scan_dir(test_id):
    scan_id = "scan-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") \
              + "-" + secrets.token_hex(2)
    d = os.path.join(scans_dir(test_id), scan_id)
    os.makedirs(d, exist_ok=True)
    return scan_id, d


def list_scans(test_id):
    d = scans_dir(test_id)
    if not os.path.isdir(d):
        return []
    out = []
    for sid in sorted(os.listdir(d), reverse=True):
        rp = os.path.join(d, sid, "result.json")
        if os.path.exists(rp):
            out.append(json.load(open(rp, encoding="utf-8")))
    return out


def load_scan(test_id, scan_id):
    rp = os.path.join(scans_dir(test_id), scan_id, "result.json")
    return json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else None
