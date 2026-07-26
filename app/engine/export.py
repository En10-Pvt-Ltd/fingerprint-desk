# SPDX-License-Identifier: Apache-2.0
"""Corpus export: turn labeled crowd captures into harness-style artifacts.

Only real photo uploads with definite ground truth are exported: feedback
'correct' (truth = the confirmed prediction) or 'wrong' with an asserted
true doc. Each capture gets a sidecar following intake.py's schema; fields
the crowd flow cannot know use the value "crowd_unknown", and extra keys
(crowd, test_id, scan_id, predicted_doc_id, judgment) are additive so
harness-style consumers that read the intake keys are unaffected. Enum
extensions live in corpus_config_crowd.json inside the zip, never in the
repo's corpus_config.json.
"""
import datetime
import glob
import json
import os
import zipfile

from . import APPDATA
from . import store, db

EXPORTS = os.path.join(APPDATA, "exports")

CROWD_ENUMS = {
    "printers": ["laser_mono", "laser_color", "inkjet", "crowd_unknown"],
    "stocks": ["crowd_unknown"],
    "phones": ["budget", "mid", "flagship", "crowd_unknown"],
    "angles": [0, 15, 30, 45],
    "lighting": ["office", "dim", "flash_glare", "window_backlight",
                 "crowd_unknown"],
    "framings": ["full", "half", "crowd_unknown"],
}


def _norm(v):
    return v if v and v != "unknown" else "crowd_unknown"


def _doc_meta_blob(manifest, doc_id):
    tdir = store.test_dir(manifest["test_id"])
    ddir = os.path.join(tdir, "docs", doc_id)
    if manifest.get("type") in ("pdf_preserved", "pdf_raster", "pdf_vector"):
        p = os.path.join(ddir, "meta.json")
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) \
            else None
    metas = []
    for p in sorted(glob.glob(os.path.join(ddir, "page*_meta.json"))):
        metas.append(json.load(open(p, encoding="utf-8")))
    return {"pages": metas} if metas else None


def build_export_zip():
    os.makedirs(EXPORTS, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y%m%d-%H%M%S")
    path = os.path.join(EXPORTS, f"crowd-export-{stamp}.zip")

    rows = db.labeled_uploads()
    manifests, written_docs = {}, set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for row in rows:
            tid = row["test_id"]
            if tid not in manifests:
                try:
                    manifests[tid] = store.load_manifest(tid)
                except FileNotFoundError:
                    manifests[tid] = None
            m = manifests[tid]
            if not m:
                continue
            true_doc = row["true_doc_id"]
            doc = next((d for d in m.get("docs", [])
                        if d["doc_id"] == true_doc), None)
            if doc is None:
                continue

            sdir = os.path.join(store.scans_dir(tid), row["scan_id"])
            imgs = [p for p in glob.glob(os.path.join(sdir, "input.*"))
                    if os.path.isfile(p)]
            if not imgs:
                continue
            img = imgs[0]
            cm = json.loads(row["capture_meta"] or "{}")
            angle = cm.get("angle", "unknown")
            capture_id = "_".join([
                f"{tid}__{true_doc}", _norm(cm.get("printer")),
                "crowd_unknown", _norm(cm.get("phone")),
                f"a{angle if angle != 'unknown' else 'x'}",
                _norm(cm.get("lighting")), _norm(cm.get("framing")),
                row["scan_id"]])
            ext = os.path.splitext(img)[1].lower()
            side = {
                "capture_id": capture_id, "doc_id": f"{tid}__{true_doc}",
                "variant": true_doc, "seed": doc.get("seed"),
                "marked": bool(doc.get("marked")),
                "printer": _norm(cm.get("printer")),
                "stock": "crowd_unknown",
                "phone": _norm(cm.get("phone")),
                "angle_deg": int(angle) if angle not in ("", "unknown")
                else None,
                "lighting": _norm(cm.get("lighting")),
                "lux_est": None,
                "framing": _norm(cm.get("framing")),
                "screen_reshoot": False,
                "applied_chain": "none", "cleanup": "none",
                "synthetic": False, "parent": None,
                "timestamp": row["created_utc"],
                # additive crowd context
                "crowd": True, "test_id": tid, "scan_id": row["scan_id"],
                "predicted_doc_id": row["predicted_doc_id"],
                "judgment": row["judgment"],
            }
            z.write(img, f"export/captures/{capture_id}{ext}")
            z.writestr(f"export/captures/{capture_id}{ext}.json",
                       json.dumps(side, indent=2))

            key = (tid, true_doc)
            if key not in written_docs:
                blob = _doc_meta_blob(m, true_doc)
                if blob is not None:
                    z.writestr(f"export/docs/{tid}__{true_doc}_meta.json",
                               json.dumps(blob))
                written_docs.add(key)

        z.writestr("export/corpus_config_crowd.json",
                   json.dumps(CROWD_ENUMS, indent=2))
        z.writestr("export/README.txt",
                   "Crowd-sourced captures with user-confirmed ground truth.\n"
                   "Sidecars follow intake.py's schema with crowd_unknown\n"
                   "for fields the crowd flow cannot verify; extra keys are\n"
                   "additive. All captures are real (synthetic: false).\n")
    return path
