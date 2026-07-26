#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Regenerate every decode JSON in this pack from its own captures/ and
metas/ directories. Self-contained provenance: run from the repo root,

    python field-test-002/make_decodes.py

and decodes/ is rebuilt from the archived inputs (the engine code in app/
is the decoder; its fingerprints are in provenance.json).
"""
import glob
import json
import math
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "app"))

from engine import pdf_scan   # noqa: E402

NAME_RE = re.compile(r"^(?P<doc>.+?)__(?P<src>v1|v2|ctrl)__p(?P<page>\d+)"
                     r".*\.(jpe?g|png)$", re.I)


def binom_p(ok, tot):
    if not tot:
        return None
    return sum(math.comb(tot, k) for k in range(ok, tot + 1)) / 2.0 ** tot


def main():
    metas = {}
    for p in glob.glob(os.path.join(HERE, "metas", "*.json")):
        doc, vname = os.path.basename(p)[:-5].split("__")
        metas.setdefault(doc, {})[vname] = json.load(open(p))
    outdir = os.path.join(HERE, "decodes")
    os.makedirs(outdir, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        for img in sorted(glob.glob(os.path.join(HERE, "captures", "*"))):
            m = NAME_RE.match(os.path.basename(img))
            if not m:
                continue
            doc, src, page = m["doc"], m["src"].lower(), int(m["page"])
            layout = metas[doc]["v1"]["pages"][page]
            obs = pdf_scan.observe_page_robust(
                img, layout, os.path.join(td, os.path.basename(img)))
            rec = {"capture": os.path.basename(img),
                   "labeled_as": {"doc": doc, "sheet": src, "page": page},
                   "carrier": "line-shift (the pdf_lineshift carrier has no "
                              "word-shift)",
                   "observation": {k: obs.get(k) for k in
                                   ("ok", "path", "deskew_deg",
                                    "n_lines_found", "reason")},
                   "scores": {}}
            if obs.get("ok"):
                for vname, meta in metas[doc].items():
                    ok, tot = pdf_scan.score_page(obs["bands"],
                                                  meta["pages"][page])
                    rec["scores"][vname] = {
                        "line_ok": ok, "line_tot": tot,
                        "line_acc": round(ok / tot, 3) if tot else None,
                        "binomial_p_one_sided": binom_p(ok, tot)}
            out = os.path.join(outdir,
                               os.path.basename(img).rsplit(".", 1)[0]
                               + ".decode.json")
            json.dump(rec, open(out, "w"), indent=1)
            print("wrote", os.path.relpath(out, REPO))


if __name__ == "__main__":
    main()
