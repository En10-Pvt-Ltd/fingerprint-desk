# SPDX-License-Identifier: Apache-2.0
"""Volunteer print packs: the no-account pack-code flow.

A pack (made by app/tools/make_volunteer_packs.py) is three print-ready
sheets — two uniquely-seeded marked variants and one unmarked control —
shuffled to anonymous letters A/B/C. Ground truth lives under
appdata/volunteer_packs/<pack_id>/private/ and is never served.

This module bridges packs into the app's existing scan machinery by
materializing each pack as a normal test directory (docs/<role>/
page0_meta.json + manifest.json) on first touch, so scan.attribute works
unchanged. Captures are recorded in pack_state.json in that test dir; the
per-sheet verdict report is WITHHELD until every sheet has at least one
capture, so a volunteer can never learn mid-experiment which sheet is the
control and (even unconsciously) treat it differently.

Pack scans deliberately live outside the users/ownership SQLite layer:
there is no account, the pack code printed on the instruction sheet is the
capability.
"""
import json
import os
import re
import secrets
import threading

from . import store

# FP + 3..12 uppercase alphanumerics: the legacy sequential codes (FP001)
# and the random codes new packs are minted with (make_volunteer_packs)
# both validate. Random codes are the real enumeration defense; the read
# routes are also rate-limited in serve.py.
PACK_RE = re.compile(r"^FP[0-9A-Z]{3,12}$")

# Unambiguous alphabet for printed codes (no 0/O, 1/I, 5/S, etc.).
_CODE_ALPHABET = "34679ACDEFHJKLMNPRTUVWXY"

# Per-pack capture ceiling: a pack has three sheets; a generous multiple
# covers honest retakes while bounding disk use on the no-account,
# per-IP-rate-limited upload route.
MAX_CAPTURES = int(os.environ.get("FF_PACK_MAX_CAPTURES", "60"))


def new_code(n=8):
    """A fresh random pack code (FP + n unambiguous chars)."""
    return "FP" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(n))

ROLE_LABELS = {"v1": "hidden mark 1", "v2": "hidden mark 2",
               "ctrl": "the unmarked control"}


def packs_root():
    return os.path.join(store.APPDATA, "volunteer_packs")


def _priv(pack_id):
    return os.path.join(packs_root(), pack_id, "private")


def exists(pack_id):
    return bool(PACK_RE.match(pack_id or "")) and \
        os.path.isfile(os.path.join(_priv(pack_id), "mapping.json"))


def mapping(pack_id):
    """letter -> {"role", "seed", "unmarked", ...} (ground truth; never
    return this to a client)."""
    with open(os.path.join(_priv(pack_id), "mapping.json"),
              encoding="utf-8") as f:
        return json.load(f)["mapping"]


def sheet_letters(pack_id):
    return sorted(mapping(pack_id))


def test_id(pack_id):
    return "pack-" + pack_id.lower()


def ensure_test(pack_id):
    """Materialize the pack as a normal test dir (idempotent) so the
    existing decoder pipeline can score captures against it."""
    tid = test_id(pack_id)
    if os.path.isfile(store.manifest_path(tid)):
        return store.load_manifest(tid)
    docs = []
    for letter, info in sorted(mapping(pack_id).items()):
        role = info["role"]
        with open(os.path.join(_priv(pack_id), f"{role}_meta.json"),
                  encoding="utf-8") as f:
            meta = json.load(f)
        marked = not info["unmarked"]
        meta.update({"test_id": tid, "doc_id": role, "page_index": 0,
                     "n_pages": 1, "marked": marked})
        ddir = os.path.join(store.test_dir(tid), "docs", role)
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir, "page0_meta.json"), "w",
                  encoding="utf-8") as f:
            json.dump(meta, f)
        docs.append({"doc_id": role, "label": ROLE_LABELS.get(role, role),
                     "marked": marked,
                     "pages": [{"page_index": 0,
                                "n_lines": meta["n_lines"]}]})
    manifest = {"test_id": tid, "name": f"Volunteer pack {pack_id}",
                "type": "pack", "status": "generated",
                "created_utc": store.now_utc(), "n_pages": 1, "docs": docs}
    store.save_manifest(manifest)
    return manifest


# ---- capture state ------------------------------------------------------------
# pack_state.json is read by the sync status route and appended to by the
# upload route; guard the read-modify-write and write atomically (temp file
# + os.replace) so a concurrent reader or a crash mid-write can never
# observe or leave behind a torn file.
_STATE_LOCK = threading.Lock()


def _state_path(pack_id):
    return os.path.join(store.test_dir(test_id(pack_id)), "pack_state.json")


def load_state(pack_id):
    try:
        with open(_state_path(pack_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # Missing or corrupt state file: start over rather than 500 the
        # no-account pack routes forever.
        return {"captures": []}


def capture_count(state):
    return len(state["captures"])


def sheets_done(state):
    """Sheets with at least one READABLE capture (one that produced a score
    table). Unreadable photos are still recorded for the corpus, but they
    don't advance the reveal gate — the volunteer gets retake guidance
    instead of burning a sheet on a photo that carries no evidence."""
    return sorted({c["sheet"] for c in state["captures"] if c.get("scores")})


def record_capture(pack_id, sheet, scan_id, result, messaging, note):
    """Append a compact capture record (enough to build the reveal report
    without re-reading scan results) and return the new state."""
    verdict = result.get("verdict") or {}
    scores = {s["doc_id"]: [s["ok"], s["tot"]]
              for s in (result.get("scores") or [])}
    with _STATE_LOCK:
        state = load_state(pack_id)
        state["captures"].append({
            "sheet": sheet, "scan_id": scan_id, "ts": store.now_utc(),
            "messaging": messaging, "note": (note or "")[:500],
            "attributed": verdict.get("doc_id"),
            "scores": scores,
            "total_bits": sum(t for _, t in scores.values()),
        })
        path = _state_path(pack_id)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, path)
    return state


def _acc(row):
    return round(row[0] / row[1], 3) if row and row[1] else None


def report(pack_id, state=None):
    """Per-sheet outcomes, one row per captured sheet, judged on the
    best-read capture (most observed bits) of that sheet."""
    state = state or load_state(pack_id)
    out = []
    for letter, info in sorted(mapping(pack_id).items()):
        caps = [c for c in state["captures"]
                if c["sheet"] == letter and c.get("scores")]
        if not caps:
            continue
        best = max(caps, key=lambda c: c.get("total_bits") or 0)
        role, marked = info["role"], not info["unmarked"]
        scores = best.get("scores") or {}
        if marked:
            row = scores.get(role)
            if best.get("attributed") == role:
                outcome = "read-correct"
                detail = (f"Sheet {letter} secretly carried "
                          f"{ROLE_LABELS[role]} — your photo identified it "
                          "correctly.")
            elif best.get("attributed"):
                outcome = "read-wrong"
                detail = (f"Sheet {letter} carried {ROLE_LABELS[role]}, but "
                          "the photo read as the other mark — a miss we "
                          "learn from.")
            else:
                outcome = "unreadable"
                detail = (f"Sheet {letter} carried a hidden mark, but it "
                          "could not be read confidently from your photo — "
                          "also a useful data point.")
        else:
            rows = [r for r in scores.values() if r and r[1]]
            row = max(rows, key=_acc) if rows else None
            if best.get("attributed"):
                outcome = "control-false-alarm"
                detail = (f"Sheet {letter} was the unmarked control but the "
                          "decoder claimed an attribution — a false positive "
                          "we take very seriously; thank you for catching "
                          "it.")
            else:
                outcome = "control-passed"
                detail = (f"Sheet {letter} was the unmarked control and the "
                          "decoder correctly refused to attribute it — the "
                          "false-accusation check passed.")
        out.append({"sheet": letter, "marked": marked, "outcome": outcome,
                    "agreement": _acc(row), "n_bits": row[1] if row else 0,
                    "detail": detail})
    return out
