#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""M3 physical-revalidation checker.

Scans every capture in appdata/m3/captures/ (naming per PROTOCOL.txt)
through the robust real-photo pipeline and scores it against both variant
metas. Gate (docs/stage2-pdf-plan.md M3): aggregate true-variant line-bit
accuracy >= 0.90 on at least one document, control captures at chance.

    python app/m3_check.py            score the dropped captures
    python app/m3_check.py --selftest verify the kit + robust pipeline on
                                      synthetic WhatsApp captures first
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from engine import pdf_scan, channel_sim   # noqa: E402

M3 = os.path.join(REPO, "appdata", "m3")
NAME_RE = re.compile(r"^(?P<doc>.+?)__(?P<src>v1|v2|ctrl|control)__"
                     r"p(?P<page>\d+).*\.(jpe?g|png)$", re.I)
GATE_ACC, GATE_MIN_BITS = 0.90, 10
CTRL_LO, CTRL_HI = 0.35, 0.65


def load_metas():
    metas = {}
    for p in glob.glob(os.path.join(M3, "meta", "*.json")):
        doc, vname = os.path.basename(p)[:-5].split("__")
        metas.setdefault(doc, {})[vname] = json.load(open(p))
    if not metas:
        sys.exit("no metas; run app/tools/m3_kit.py first")
    return metas


def score_capture(img_path, doc, page, metas, workdir):
    layout = metas[doc]["v1"]["pages"][page]
    obs = pdf_scan.observe_page_robust(img_path, layout, workdir)
    row = {"obs": obs, "scores": {}}
    if obs.get("ok"):
        for vname, meta in metas[doc].items():
            ok, tot = pdf_scan.score_page(obs["bands"], meta["pages"][page])
            row["scores"][vname] = (ok, tot)
    return row


def selftest(metas):
    """Round-trip the robust pipeline on synthetic WhatsApp captures of the
    kit's own PDFs, so the physical run never fails on tooling."""
    import fitz
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        for doc, vs in metas.items():
            pdf = os.path.join(M3, "print", f"{doc}__v1.pdf")
            d = fitz.open(pdf)
            png = os.path.join(td, f"{doc}.png")
            d[0].get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72),
                            colorspace=fitz.csGRAY, alpha=False).save(png)
            d.close()
            cap, _ = channel_sim.simulate(png, td, "whatsapp")
            row = score_capture(cap, doc, 0, metas, os.path.join(td, "w"))
            ok, tot = row["scores"].get("v1", (0, 0))
            state = "ok" if (tot and ok / tot >= 0.95) else "FAIL"
            if state == "FAIL":
                fails += 1
            print(f"  {state:4s} {doc}: path={row['obs'].get('path')} "
                  f"v1 {ok}/{tot}")
    if fails:
        sys.exit("M3 selftest FAILED")
    print("M3 selftest passed: kit PDFs decode through the robust pipeline.")


def identify(metas):
    """Name-agnostic sheet identification: for EVERY image in captures/,
    try every (doc, page) layout and report what the geometry says the
    photo actually shows. Use this to resolve sheet mix-ups; filenames are
    ignored entirely."""
    import math
    files = [p for p in glob.glob(os.path.join(M3, "captures", "*"))
             if os.path.isfile(p)]
    with tempfile.TemporaryDirectory() as td:
        for p in sorted(files):
            base = os.path.basename(p)
            best = None
            for doc, vs in metas.items():
                for page in range(vs["v1"]["n_pages"]):
                    if not vs["v1"]["pages"][page]["bands"]:
                        continue
                    row = score_capture(p, doc, page, metas,
                                        os.path.join(td, base + f"{doc}{page}"))
                    if not row["obs"].get("ok"):
                        continue
                    for vname, (ok, tot) in row["scores"].items():
                        if not tot:
                            continue
                        pv = sum(math.comb(tot, k)
                                 for k in range(ok, tot + 1)) / 2.0 ** tot
                        cand = (pv, doc, page, vname, ok, tot,
                                row["obs"]["path"])
                        if best is None or pv < best[0]:
                            best = cand
            if best is None:
                print(f"  {base}: no document layout matched (foreign "
                      "document or unreadable capture)")
                continue
            pv, doc, page, vname, ok, tot, path = best
            if pv <= 1e-3:
                print(f"  {base}: {doc} page {page + 1}, sheet = {vname} "
                      f"({ok}/{tot} line bits, p = {pv:.1e}) [{path}]")
            else:
                print(f"  {base}: layout matches {doc} page {page + 1} but "
                      f"no variant separates from chance (best {vname} "
                      f"{ok}/{tot}, p = {pv:.2f}); likely the CONTROL sheet "
                      f"or too degraded [{path}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--identify", action="store_true",
                    help="ignore filenames; report which sheet each photo "
                         "in captures/ actually shows")
    args = ap.parse_args()
    metas = load_metas()
    if args.selftest:
        selftest(metas)
        return
    if args.identify:
        identify(metas)
        return

    caps = [p for p in glob.glob(os.path.join(M3, "captures", "*"))
            if NAME_RE.match(os.path.basename(p))]
    unrecognized = [p for p in glob.glob(os.path.join(M3, "captures", "*"))
                    if os.path.isfile(p)
                    and not NAME_RE.match(os.path.basename(p))]
    for p in unrecognized:
        print(f"  NOTE ignoring unrecognized name: {os.path.basename(p)} "
              "(see PROTOCOL.txt)")
    if not caps:
        print("READY: no captures yet. Print appdata/m3/print/, follow "
              "appdata/m3/PROTOCOL.txt, drop received WhatsApp files into "
              "appdata/m3/captures/, then rerun this.")
        return

    agg_true = collections.defaultdict(lambda: [0, 0])   # doc -> ok, tot
    agg_ctrl = [0, 0]
    fails = []
    print(f"{'capture':44s} {'pipeline':18s} {'v1':>9s} {'v2':>9s} verdict")
    with tempfile.TemporaryDirectory() as td:
        for p in sorted(caps):
            m = NAME_RE.match(os.path.basename(p))
            doc, src, page = m["doc"], m["src"].lower(), int(m["page"])
            src = "ctrl" if src in ("ctrl", "control") else src
            if doc not in metas:
                fails.append(f"{os.path.basename(p)}: unknown doc {doc!r}")
                continue
            row = score_capture(p, doc, page, metas,
                                os.path.join(td, os.path.basename(p)))
            obs = row["obs"]
            if not obs.get("ok"):
                print(f"{os.path.basename(p):44s} {'(failed)':18s} "
                      f"{'-':>9s} {'-':>9s} {obs.get('reason')}")
                fails.append(f"{os.path.basename(p)}: {obs.get('reason')}")
                continue
            cells = {}
            for vname in ("v1", "v2"):
                ok, tot = row["scores"][vname]
                cells[vname] = f"{ok}/{tot}" if tot else "n/a"
                if src == vname:
                    agg_true[doc][0] += ok
                    agg_true[doc][1] += tot
                elif src == "ctrl":
                    agg_ctrl[0] += ok
                    agg_ctrl[1] += tot
            print(f"{os.path.basename(p):44s} {obs['path']:18s} "
                  f"{cells['v1']:>9s} {cells['v2']:>9s} "
                  f"{'control' if src == 'ctrl' else 'true=' + src}")

    print("\nper-document true-variant aggregate:")
    doc_pass = []
    for doc, (ok, tot) in sorted(agg_true.items()):
        acc = ok / tot if tot else None
        state = ""
        if tot >= GATE_MIN_BITS and acc >= GATE_ACC:
            state = "  << clears the M3 gate"
            doc_pass.append(doc)
        print(f"  {doc}: {ok}/{tot}"
              + (f" = {acc:.3f}{state}" if tot else "  (no bits)"))
    if agg_ctrl[1]:
        cacc = agg_ctrl[0] / agg_ctrl[1]
        print(f"control aggregate: {agg_ctrl[0]}/{agg_ctrl[1]} = {cacc:.3f}"
              + ("" if CTRL_LO <= cacc <= CTRL_HI or agg_ctrl[1] < 8
                 else "  << OUTSIDE the chance band, investigate"))
    else:
        print("control aggregate: no control captures yet (the gate needs "
              "them; a GO without the control is not valid)")

    print()
    if fails:
        for f in fails:
            print("  ISSUE", f)
    if doc_pass and agg_ctrl[1] >= 8 and \
       CTRL_LO <= agg_ctrl[0] / agg_ctrl[1] <= CTRL_HI:
        print(f"M3 GATE PASSED on {', '.join(doc_pass)}: the formatting-"
              "preserving mark survives the physical channel, control at "
              "chance.")
    else:
        print("M3 gate not yet decided: need a passing document AND control "
              "captures at chance. Keep collecting per PROTOCOL.txt.")


if __name__ == "__main__":
    main()
