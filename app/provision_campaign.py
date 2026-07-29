#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One-shot: bulk-create a print-and-photograph campaign in the app's real
appdata DB and share it in assigned mode (one unique copy auto-assigned per
contributor). Drives the same HTTP endpoints the browser uses (FastAPI
TestClient, in-process) so the result is identical to a UI-created campaign.
Idempotent-ish: refuses if a same-named campaign already exists.

Document, name, and copy count are all configurable, so it works on a fresh
clone with no external files (defaults to the app's own sample text):

    FF_FONT_PATH=... \\
        FF_PROVISION_DOC=path/to/document.txt \\
        FF_PROVISION_NAME="Midterm A" FF_PROVISION_VARIANTS=300 \\
        python app/provision_campaign.py

Runs in-process (no sockets, nothing served), so it uses local mode: the
implicit local operator -- always an admin -- creates and owns the
campaign. On a server-mode deployment any admin account can still manage
it (share/funnel are owner-or-admin).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# In-process TestClient run: local mode's implicit operator is the admin
# (no password needed; nothing is bound to any network interface).
os.environ["FF_MODE"] = "local"
os.environ.setdefault("FF_MAX_CAMPAIGN_VARIANTS", "300")

DOC = os.environ.get("FF_PROVISION_DOC")    # optional .txt; else sample text
NAME = os.environ.get("FF_PROVISION_NAME", "Print & photograph campaign")
N_VARIANTS = int(os.environ.get("FF_PROVISION_VARIANTS", "25"))

from fastapi.testclient import TestClient   # noqa: E402
from serve import app                       # noqa: E402
from engine import APPDATA, render           # noqa: E402


def main():
    if DOC:
        content = open(DOC, encoding="utf-8").read()
        src = DOC
    else:
        content = render.SAMPLE_TEXT         # bundled, always present
        src = "built-in sample text"
    print(f"appdata:   {APPDATA}")
    print(f"document:  {src} ({len(content.split())} words)")

    c = TestClient(app, raise_server_exceptions=True)
    me = c.get("/api/me").json()
    c.headers["X-CSRF-Token"] = me["csrf"]
    print(f"operator:  {me['email']}")
    assert me["is_admin"], "the local-mode operator must be admin"

    for t in c.get("/api/tests").json():
        if t["name"] == NAME:
            sys.exit(f"a campaign named {NAME!r} already exists: {t['test_id']}"
                     " -- refusing to create a duplicate.")

    print(f"creating {N_VARIANTS} variants + 1 control ...")
    r = c.post("/api/tests", json={
        "name": NAME,
        "content": content,
        "variant_labels": [f"Copy {i + 1}" for i in range(N_VARIANTS)],
        "n_controls": 1,
        "mode": "rendered",
        "sample_used": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    tid = body["test_id"]
    print(f"  test_id: {tid}")
    print(f"  capacity_warning: {body.get('capacity_warning')}")

    print("generating (300 renders, a few minutes) ...")
    t0 = time.time()
    while True:
        m = c.get(f"/api/tests/{tid}").json()
        st = m["status"]
        if st == "generated":
            break
        if st == "error":
            sys.exit(f"generation error: {m.get('error')}")
        if time.time() - t0 > 1800:
            sys.exit("generation timed out")
        time.sleep(3.0)
    n_marked = sum(1 for d in m.get("docs", []) if d["marked"])
    print(f"  generated in {time.time() - t0:.0f}s: {n_marked} marked + "
          f"{len(m['docs']) - n_marked} control, {m['n_pages']} pages")

    print("sharing in assigned mode ...")
    r = c.post(f"/api/admin/tests/{tid}/share",
               json={"shared": True, "assigned": True})
    assert r.status_code == 200, r.text
    s = r.json()
    print(f"  shared={s['shared']} assign_mode={s['assign_mode']} "
          f"capacity_warning={s.get('capacity_warning')}")

    f = c.get(f"/api/tests/{tid}/funnel").json()
    print(f"  funnel: {f}")
    print(f"\nDONE. Campaign {tid!r} is live and shared.")
    print("Contributors who sign in will be auto-assigned one of the "
          f"{n_marked} copies.")


if __name__ == "__main__":
    main()
