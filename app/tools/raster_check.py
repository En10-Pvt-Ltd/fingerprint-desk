#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End-to-end check of raster line-shift fingerprinting on an image-only PDF.

    python app/tools/raster_check.py --pdf paper.pdf --pages 5 \
        --seeds 5101 5102 --out field-test-raster

Emits v1/v2 (marked) + control (byte copy) PDFs with metas, verifies the
formatting guarantee (pixel changes confined to shifted line bands; pages
outside the marked range untouched), then runs the synthetic decode matrix
(clean / whatsapp / double presets) scoring every capture against every
variant's meta plus cross-variant and control reads.

Synthetic-channel numbers verify decoder logic only — the physical
operating point needs a real print -> phone -> WhatsApp pass (M3 protocol).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
REPO = os.path.dirname(APP)
for p in (APP, REPO, os.path.join(REPO, "robust_decode")):
    sys.path.insert(0, p)

import cv2                    # noqa: E402
import fitz                   # noqa: E402
import numpy as np            # noqa: E402

from engine import raster_mark, channel_sim   # noqa: E402


def fail(msg):
    print(f"FAIL  {msg}")
    sys.exit(1)


def render_page(pdf_bytes, pno, dpi, path):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    doc[pno].get_pixmap(dpi=dpi).save(path)
    doc.close()
    return path


def native_image(pdf_bytes, pno):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rgb, _ = raster_mark._page_image(doc, pno)
    doc.close()
    return rgb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages", type=int, default=5)
    ap.add_argument("--seeds", type=int, nargs=2, default=[5101, 5102])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    wd = os.path.join(args.out, "work")
    os.makedirs(wd, exist_ok=True)
    src = open(args.pdf, "rb").read()
    pages = range(args.pages)

    print(f"[1] capacity analysis (first {args.pages} pages)")
    ana = raster_mark.analyze(src, pages)
    total = sum(len(pg["triplets"]) for pg in ana)
    for pg in ana:
        print(f"  page {pg['page_index']}: {len(pg['runs'])} line runs, "
              f"{len(pg['triplets'])} markable triplets")
    print(f"  total slots: {total}")
    if total < 8:
        fail("fewer than 8 slots across the marked pages")

    print("[2] embed variants + control")
    variants = {}
    for vi, seed in enumerate(args.seeds, start=1):
        pdf_bytes, meta = raster_mark.embed(src, seed, pages=pages)
        variants[f"v{vi}"] = (pdf_bytes, meta)
        open(os.path.join(args.out, f"v{vi}.pdf"), "wb").write(pdf_bytes)
        json.dump(meta, open(os.path.join(args.out, f"v{vi}_meta.json"), "w"),
                  indent=1)
        print(f"  v{vi}: seed={seed} slots={meta['n_slots']}")
    ctrl_bytes, ctrl_meta = raster_mark.embed(src, args.seeds[0], pages=pages,
                                             unmarked=True)
    if ctrl_bytes != src:
        fail("control is not a byte copy of the source")
    open(os.path.join(args.out, "control.pdf"), "wb").write(ctrl_bytes)
    json.dump(ctrl_meta, open(os.path.join(args.out, "control_meta.json"),
                              "w"), indent=1)
    print("  control: byte copy of source  OK")

    print("[3] formatting guarantee (native-image pixel diff)")
    for vname, (pdf_bytes, meta) in variants.items():
        for pg in meta["pages"]:
            pno = pg["page_index"]
            a0 = native_image(src, pno).astype(np.int16)
            a1 = native_image(pdf_bytes, pno).astype(np.int16)
            if a0.shape != a1.shape:
                fail(f"{vname} p{pno}: image dimensions changed")
            diff = (np.abs(a0 - a1).max(axis=2) > 0)
            rows = np.where(diff.any(axis=1))[0]
            spans = [(min(s["mid"][0] - raster_mark.SHIFT_PX - 1,
                          s["mid"][0] - 2),
                      s["mid"][1] + raster_mark.SHIFT_PX + 1)
                     for s in pg["slots"] if s["delta_px"] != 0]
            stray = [int(r) for r in rows
                     if not any(lo <= r < hi for lo, hi in spans)]
            if stray:
                fail(f"{vname} p{pno}: {len(stray)} changed rows outside "
                     f"shifted bands, e.g. {stray[:6]}")
            print(f"  {vname} p{pno}: {int(diff.sum())} px changed, all "
                  f"inside {len(spans)} shifted line bands")
        # pages outside the marked range: identical rendered content
        dsrc = fitz.open(stream=src, filetype="pdf")
        dmk = fitz.open(stream=pdf_bytes, filetype="pdf")
        for pno in range(args.pages, min(args.pages + 2, dsrc.page_count)):
            p0 = dsrc[pno].get_pixmap(dpi=72)
            p1 = dmk[pno].get_pixmap(dpi=72)
            if p0.samples != p1.samples:
                fail(f"{vname} p{pno}: unmarked page render changed")
        dsrc.close()
        dmk.close()
        print(f"  {vname}: unmarked pages render byte-identical  OK")

    print("[4] decode matrix (synthetic channel; logic verification only)")
    presets = ["clean", "whatsapp", "double"]
    results = []
    for vname, (pdf_bytes, meta) in variants.items():
        other = "v2" if vname == "v1" else "v1"
        ometa = variants[other][1]
        for pg in meta["pages"]:
            pno = pg["page_index"]
            png = os.path.join(wd, f"{vname}_p{pno}.png")
            render_page(pdf_bytes, pno, 300, png)
            for preset in presets:
                pwd = os.path.join(wd, f"{vname}_p{pno}_{preset}")
                os.makedirs(pwd, exist_ok=True)
                cap, _ = channel_sim.simulate(png, pwd, preset)
                obs = raster_mark.observe(cap, pg)
                if not obs.get("ok"):
                    results.append((vname, pno, preset, None, None, None,
                                    obs.get("reason")))
                    continue
                ok, tot = raster_mark.score(obs, pg)
                xok, xtot = raster_mark.score(obs, ometa["pages"]
                                              [meta["pages"].index(pg)])
                results.append((vname, pno, preset, (ok, tot), (xok, xtot),
                                obs["quality"], None))

    print(f"\n  {'variant':8s}{'page':6s}{'preset':10s}"
          f"{'true-acc':12s}{'cross-acc':12s}{'quality':8s}")
    agg = {}
    for vname, pno, preset, true, cross, q, err in results:
        if err:
            print(f"  {vname:8s}{pno:<6d}{preset:10s}OBS-FAIL: {err}")
            continue
        ta = f"{true[0]}/{true[1]}={true[0]/true[1]:.2f}" if true[1] else "-"
        xa = (f"{cross[0]}/{cross[1]}={cross[0]/cross[1]:.2f}"
              if cross[1] else "-")
        print(f"  {vname:8s}{pno:<6d}{preset:10s}{ta:12s}{xa:12s}{q:<8.2f}")
        a = agg.setdefault(preset, [0, 0, 0, 0])
        a[0] += true[0]
        a[1] += true[1]
        a[2] += cross[0]
        a[3] += cross[1]

    print("\n  aggregate per preset:")
    verdicts = {}
    for preset in presets:
        a = agg.get(preset, [0, 0, 0, 0])
        t = a[0] / a[1] if a[1] else 0.0
        x = a[2] / a[3] if a[3] else 0.0
        verdicts[preset] = {"true_ok": a[0], "true_tot": a[1],
                            "true_acc": round(t, 3),
                            "cross_ok": a[2], "cross_tot": a[3],
                            "cross_acc": round(x, 3)}
        print(f"  {preset:10s} true {a[0]}/{a[1]} = {t:.3f}   "
              f"cross {a[2]}/{a[3]} = {x:.3f}")

    print("[5] control (unmarked) decode — must sit in the chance band")
    ctl_agree = ctl_tot = 0
    v1meta = variants["v1"][1]
    for pg in v1meta["pages"]:
        pno = pg["page_index"]
        png = os.path.join(wd, f"ctrl_p{pno}.png")
        render_page(ctrl_bytes, pno, 300, png)
        pwd = os.path.join(wd, f"ctrl_p{pno}_whatsapp")
        os.makedirs(pwd, exist_ok=True)
        cap, _ = channel_sim.simulate(png, pwd, "whatsapp")
        obs = raster_mark.observe(cap, pg)
        if not obs.get("ok"):
            continue
        for si, sl in enumerate(pg["slots"]):
            ob = obs["bits"].get(si)
            if ob is None:
                continue
            ctl_tot += 1
            ctl_agree += int(ob == sl["bit"])
    ctl_acc = ctl_agree / ctl_tot if ctl_tot else None
    print(f"  control vs v1 meta (whatsapp): {ctl_agree}/{ctl_tot}"
          f"{'' if ctl_acc is None else f' = {ctl_acc:.3f}'}"
          f"  ({'chance band' if ctl_acc is None or 0.25 <= ctl_acc <= 0.75 else 'OUT OF BAND — decoder reads layout, results invalid'})")
    verdicts["control_whatsapp"] = {"agree": ctl_agree, "tot": ctl_tot,
                                    "acc": ctl_acc}

    wa = verdicts.get("whatsapp", {})
    t = wa.get("true_acc", 0.0)
    x = wa.get("cross_acc", 0.0)
    print(f"\n  WhatsApp-preset verdict: true-variant {t:.3f} "
          f"({'>= 0.90 target met' if t >= 0.90 else 'BELOW 0.90 target'}), "
          f"cross-variant {x:.3f} "
          f"({'chance band' if 0.30 <= x <= 0.70 else 'OUT OF CHANCE BAND'})")
    print("  (synthetic channel: decoder-logic verification, not a "
          "physical result)")

    json.dump({"results": [
        {"variant": v, "page": p, "preset": pr,
         "true": t, "cross": c, "quality": q, "error": e}
        for v, p, pr, t, c, q, e in results],
        "aggregate": verdicts},
        open(os.path.join(args.out, "decode_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
