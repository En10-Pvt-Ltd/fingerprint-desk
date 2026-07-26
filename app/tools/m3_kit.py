#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build the M3 physical-revalidation kit: print-ready fingerprinted PDFs,
ground-truth metas, the capture drop folder and the printed protocol.

    python app/tools/m3_kit.py

Output (appdata/m3/):
  print/<doc>__v1.pdf, <doc>__v2.pdf, <doc>__control.pdf   print these
  meta/<doc>__v1.json, __v2.json                            ground truth
  captures/                                                 drop photos here
  manifest.json, PROTOCOL.txt
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
REPO = os.path.dirname(APP)
sys.path.insert(0, APP)

from engine import pdf_mark  # noqa: E402

DOCS = ["doc01_times11", "doc02_helv_headings"]
SEEDS = {"v1": 7001, "v2": 7002}
M3 = os.path.join(REPO, "appdata", "m3")

PROTOCOL = """M3 PHYSICAL REVALIDATION PROTOCOL
=================================

Goal: does the 0.48 pt line-shift survive real print + phone photo +
WhatsApp in foreign fonts and layouts? Gate: line-bit accuracy >= 0.90 on
at least one document, control at chance.

1. PRINT everything in print/ at ACTUAL SIZE / 100%, never "fit to page"
   (scaling destroys the sub-pixel geometry). Mono laser preferred.
   Write the file name on the REVERSE of each sheet only.

2. PHOTOGRAPH page 1 of each printed sheet (page 2 of doc01 optional,
   more data is better): hand-held, roughly upright, whole text block in
   frame, ordinary indoor light. One photo per sheet is enough.

3. WHATSAPP HOP: send each photo through one real WhatsApp hop (to a
   second account or a contact), then download the RECEIVED file.

4. NAME the received files and drop them into captures/:
      <doc>__<source>__p<page>.jpg
   e.g. doc01_times11__v1__p0.jpg
        doc01_times11__ctrl__p0.jpg
        doc02_helv_headings__v2__p0.jpg
   (extra suffixes are fine: doc01_times11__v1__p0__take2.jpg)

5. RUN:  python app/m3_check.py
"""


def main():
    for sub in ("print", "meta", "captures"):
        os.makedirs(os.path.join(M3, sub), exist_ok=True)
    manifest = {"seeds": SEEDS, "docs": {}}
    for doc in DOCS:
        src_path = os.path.join(REPO, "appdata", "m1", "corpus", f"{doc}.pdf")
        src = open(src_path, "rb").read()
        entry = {"n_pages": None, "slots": {}}
        for vname, seed in SEEDS.items():
            data, meta = pdf_mark.embed(src, seed)
            open(os.path.join(M3, "print", f"{doc}__{vname}.pdf"),
                 "wb").write(data)
            json.dump(meta, open(os.path.join(M3, "meta",
                                              f"{doc}__{vname}.json"), "w"))
            entry["n_pages"] = meta["n_pages"]
            entry["slots"][vname] = meta["n_applied"]
        shutil.copyfile(src_path,
                        os.path.join(M3, "print", f"{doc}__control.pdf"))
        manifest["docs"][doc] = entry
        print(f"{doc}: {entry['n_pages']} page(s), "
              f"slots {entry['slots']}")
    json.dump(manifest, open(os.path.join(M3, "manifest.json"), "w"),
              indent=1)
    open(os.path.join(M3, "PROTOCOL.txt"), "w", encoding="utf-8") \
        .write(PROTOCOL)
    print(f"\nkit ready: {M3}")
    print("print everything in print/, then follow PROTOCOL.txt")


if __name__ == "__main__":
    main()
