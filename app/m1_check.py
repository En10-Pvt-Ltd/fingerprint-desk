#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""M1 acceptance checker: formatting-preserving embedding round-trip.

For every corpus PDF and two seeds: embed, rasterize original and variant at
300 dpi, and verify per line (from the meta, never hand-typed):
  - every applied marked line's measured baseline moved by exactly the
    embedded shift (tolerance 0.3 px),
  - every control / unapplied line moved by 0 (tolerance 0.3 px),
  - the pixel difference OUTSIDE the applied marked lines' row spans is
    exactly zero (no reflow, nothing else touched).

    python app/m1_check.py [--corpus appdata/m1/corpus]
"""
import argparse
import glob
import os
import sys

import fitz
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from engine import pdf_mark          # noqa: E402
import decode as dec                 # noqa: E402

DPI = 300
SCALE = DPI / 72.0
TOL_PX = 0.3
SEEDS = (5001, 5002)

FAILS = []


def raster(doc_bytes):
    doc = fitz.open(stream=doc_bytes, filetype="pdf")
    mats = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE),
                              colorspace=fitz.csGRAY, alpha=False)
        mats.append(np.frombuffer(pix.samples, dtype=np.uint8)
                    .reshape(pix.height, pix.width).copy())
    doc.close()
    return mats


def measure(gray, y_px, pitch_px):
    """Ink-weighted row centroid of the single text-line run nearest the
    expected baseline. Identical text merely translated gives an exactly
    translated centroid, so orig-vs-variant deltas are sub-pixel exact.
    (decode.line_baseline is unsuitable here: it pads its band and swallows
    neighboring lines at small pitches.)"""
    a = max(0, int(round(y_px - 0.7 * pitch_px)))
    b = min(gray.shape[0], int(round(y_px + 0.7 * pitch_px)))
    ink = (255.0 - gray[a:b].astype(np.float64)).sum(axis=1)
    if ink.max() <= 0:
        return None
    on = ink > 0.02 * ink.max()
    runs, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(on)))
    if not runs:
        return None
    # Merge runs split by hairline gaps (descender rows often detach).
    gap = max(2, int(0.08 * pitch_px))
    merged = [runs[0]]
    for s2, e2 in runs[1:]:
        if s2 - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], e2)
        else:
            merged.append((s2, e2))
    runs = merged
    target = y_px - a
    # the run whose span is nearest the expected baseline row
    s, e = min(runs, key=lambda r: min(abs(target - r[0]), abs(target - r[1]),
                                       0 if r[0] <= target <= r[1] else 1e9))
    w = ink[s:e]
    rows = np.arange(s, e)
    return a + float((rows * w).sum() / w.sum())


def check_doc(path):
    name = os.path.basename(path)
    src = open(path, "rb").read()
    orig_imgs = raster(src)
    rows_stats = []
    for seed in SEEDS:
        var, meta = pdf_mark.embed(src, seed)
        var_imgs = raster(var)
        n_marked = n_applied = n_checked = 0
        worst_marked = worst_still = 0.0
        for pg in meta["pages"]:
            pi = pg["page_index"]
            go, gv = orig_imgs[pi], var_imgs[pi]
            excl = np.zeros(go.shape[0], bool)
            for band in pg["bands"]:
                pitch_px = band["pitch_pt"] * SCALE
                for line in band["lines"]:
                    y = line["y_px300"]
                    bo = measure(go, y, pitch_px)
                    bv = measure(gv, y, pitch_px)
                    if bo is None or bv is None:
                        FAILS.append(f"{name}/s{seed}/p{pi}: baseline "
                                     f"unmeasurable at y={y}")
                        continue
                    d = bv - bo
                    exp = -line["delta_pt"] * SCALE
                    n_checked += 1
                    if line["role"] == "marked":
                        n_marked += 1
                    if line["applied"]:
                        n_applied += 1
                        worst_marked = max(worst_marked, abs(d - exp))
                        if abs(d - exp) > TOL_PX:
                            FAILS.append(
                                f"{name}/s{seed}/p{pi}: marked line at y={y} "
                                f"moved {d:+.2f}px, expected {exp:+.2f}px "
                                f"({line['text_head'][:25]!r})")
                        lo = int(y - pitch_px)
                        hi = int(y + pitch_px)
                        excl[max(0, lo):min(len(excl), hi)] = True
                    else:
                        worst_still = max(worst_still, abs(d))
                        if abs(d) > TOL_PX:
                            FAILS.append(
                                f"{name}/s{seed}/p{pi}: unmarked line at "
                                f"y={y} moved {d:+.2f}px "
                                f"({line['text_head'][:25]!r})")
            diff = np.abs(go.astype(np.int16) - gv.astype(np.int16))
            outside = diff[~excl]
            if outside.size and outside.max() > 0:
                bad = int(np.where(~excl)[0][np.argmax(outside.max(axis=1))])
                FAILS.append(f"{name}/s{seed}/p{pi}: pixels changed outside "
                             f"marked rows (max {int(outside.max())} at "
                             f"row {bad}): reflow or stray edit")
        rows_stats.append((seed, meta["n_slots"], n_applied, n_marked,
                           n_checked, worst_marked, worst_still))
    return rows_stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(REPO, "appdata", "m1",
                                                     "corpus"))
    args = ap.parse_args()
    pdfs = sorted(glob.glob(os.path.join(args.corpus, "*.pdf")))
    if not pdfs:
        sys.exit("no corpus; run app/tools/m1_corpus.py first")

    print(f"{'document':24s} {'seed':>5s} {'slots':>5s} {'applied':>7s} "
          f"{'checked':>7s} {'worst mark err':>14s} {'worst still err':>15s}")
    total_applied = 0
    for p in pdfs:
        for (seed, slots, applied, marked, checked, wm, ws) in check_doc(p):
            total_applied += applied
            print(f"{os.path.basename(p):24s} {seed:5d} {slots:5d} "
                  f"{applied:7d} {checked:7d} {wm:11.3f} px {ws:12.3f} px")

    print()
    if FAILS:
        for f in FAILS[:40]:
            print("  FAIL", f)
        sys.exit(f"M1 CHECK FAILED: {len(FAILS)} problem(s)")
    if total_applied == 0:
        sys.exit("M1 CHECK FAILED: no line was ever marked")
    print(f"M1 CHECK PASSED: {total_applied} marked-line embeddings verified "
          f"across {len(pdfs)} documents x {len(SEEDS)} seeds; zero movement "
          "elsewhere; zero pixel change outside marked rows.")


if __name__ == "__main__":
    main()
