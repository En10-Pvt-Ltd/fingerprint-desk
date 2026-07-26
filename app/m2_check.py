#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""M2 acceptance: synthetic-channel decode of formatting-preserved variants.

For every corpus PDF: embed 3 variants (distinct seeds), rasterize each page
at 300 dpi, push through channel.py presets (clean / whatsapp / harsh), and
blind-decode band triplets (engine/pdf_scan.py). The unmarked original runs
the same gauntlet as the control.

Gates (clean and whatsapp presets; harsh is reported as ungated stress
data, consistent with the research repo where the harsh preset costs the
native encoder a line bit too):
  - every (doc, variant): aggregate line-bit accuracy vs the TRUE variant
    >= 0.95 at clean and whatsapp;
  - control captures scored against all variants: global accuracy in
    [0.40, 0.60] per preset;
  - segmentation must succeed on every clean/whatsapp capture. Documents
    whose bands sit below pdf_mark.MIN_PITCH_MARK carry no marks by design
    and are skipped (the measured pitch floor from this harness).

    python app/m2_check.py [--corpus appdata/m1/corpus]
"""
import argparse
import collections
import glob
import os
import sys
import tempfile

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from engine import pdf_mark, pdf_scan, channel_sim   # noqa: E402

DPI = 300
SEEDS = (6001, 6002, 6003)
PRESETS = ("clean", "whatsapp", "harsh")
GATED_PRESETS = ("clean", "whatsapp")
TRUE_ACC_GATE = 0.95
CTRL_LO, CTRL_HI = 0.40, 0.60

FAILS = []


def raster_page(doc_bytes, pno, out_png):
    doc = fitz.open(stream=doc_bytes, filetype="pdf")
    pix = doc[pno].get_pixmap(matrix=fitz.Matrix(DPI / 72, DPI / 72),
                              colorspace=fitz.csGRAY, alpha=False)
    pix.save(out_png)
    doc.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(REPO, "appdata", "m1",
                                                     "corpus"))
    args = ap.parse_args()
    pdfs = sorted(glob.glob(os.path.join(args.corpus, "*.pdf")))
    if not pdfs:
        sys.exit("no corpus; run app/tools/m1_corpus.py first")

    # (doc, source, preset, scored_vs) -> [ok, tot]
    agg = collections.defaultdict(lambda: [0, 0])
    seg_fail = []

    with tempfile.TemporaryDirectory() as td:
        for path in pdfs:
            name = os.path.basename(path).replace(".pdf", "")
            src = open(path, "rb").read()
            variants = [(f"v{i+1}", *pdf_mark.embed(src, s))
                        for i, s in enumerate(SEEDS)]
            layout = variants[0][2]                  # band structure reference
            sources = [(v[0], v[1]) for v in variants] + [("ctrl", src)]
            for pno in range(layout["n_pages"]):
                pmeta = layout["pages"][pno]
                if not pmeta["bands"]:
                    continue
                for sname, sbytes in sources:
                    png = os.path.join(td, f"{name}_{sname}_p{pno}.png")
                    raster_page(sbytes, pno, png)
                    for preset in PRESETS:
                        wd = os.path.join(td, f"{name}_{sname}_p{pno}_{preset}")
                        os.makedirs(wd, exist_ok=True)
                        cap, _ = channel_sim.simulate(png, wd, preset)
                        obs = pdf_scan.observe_page(cap, pmeta)
                        if not obs.get("ok"):
                            seg_fail.append(f"{name}/{sname}/p{pno}/{preset}: "
                                            f"{obs.get('reason')}")
                            continue
                        for vname, _vb, vmeta in variants:
                            ok, tot = pdf_scan.score_page(
                                obs["bands"], vmeta["pages"][pno])
                            a = agg[(name, sname, preset, vname)]
                            a[0] += ok
                            a[1] += tot
            print(f"decoded {name}", flush=True)

    print(f"\n{'document':22s} {'preset':9s} {'true acc':>12s} "
          f"{'wrong-variant accs':>24s}")
    docs = sorted({k[0] for k in agg})
    for d in docs:
        for preset in PRESETS:
            trues, wrongs = [], []
            for (dd, sname, pp, vname), (ok, tot) in agg.items():
                if dd != d or pp != preset or sname == "ctrl" or tot == 0:
                    continue
                (trues if sname == vname else wrongs).append((ok, tot))
            if not trues:
                continue
            t_ok = sum(o for o, _ in trues)
            t_tot = sum(t for _, t in trues)
            acc = t_ok / t_tot
            w = ", ".join(f"{o/t:.2f}" for o, t in wrongs) or "n/a"
            tag = "" if preset in GATED_PRESETS else "  (stress, ungated)"
            print(f"{d:22s} {preset:9s} {t_ok:4d}/{t_tot:<4d}= {acc:5.3f} "
                  f"{w:>24s}{tag}")
            if preset in GATED_PRESETS and acc < TRUE_ACC_GATE:
                FAILS.append(f"{d}/{preset}: true-variant accuracy "
                             f"{acc:.3f} < {TRUE_ACC_GATE}")

    print("\ncontrol captures scored against all variants:")
    for preset in PRESETS:
        ok = tot = 0
        for (dd, sname, pp, vname), (o, t) in agg.items():
            if sname == "ctrl" and pp == preset:
                ok += o
                tot += t
        if tot:
            acc = ok / tot
            print(f"  {preset:9s} {ok:4d}/{tot:<4d} = {acc:.3f}")
            if not (CTRL_LO <= acc <= CTRL_HI):
                FAILS.append(f"control/{preset}: accuracy {acc:.3f} outside "
                             f"[{CTRL_LO}, {CTRL_HI}]")

    if seg_fail:
        print("\nsegmentation failures:")
        for s in seg_fail:
            preset = s.split("/")[3].split(":")[0]
            info = "" if preset in GATED_PRESETS else "  (stress, ungated)"
            print("  ", s + info)
            if preset in GATED_PRESETS:
                FAILS.append(f"segmentation: {s}")

    print()
    if FAILS:
        for f in FAILS:
            print("  FAIL", f)
        sys.exit(f"M2 CHECK FAILED: {len(FAILS)} problem(s)")
    print("M2 CHECK PASSED: all variants decode at >= 0.95 through the "
          "gated presets (clean, whatsapp); controls read at chance; no "
          "gated-preset segmentation failures. Harsh rows above are "
          "ungated stress data.")


if __name__ == "__main__":
    main()
