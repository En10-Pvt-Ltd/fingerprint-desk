#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real-capture robustness pipeline for Carrier 1, parameterized.

This is the single-command version of the pipeline that produced the only
real-world result to date (received.jpeg -> line-shift 14/15 = 0.933,
word-shift 355 erasures). It reproduces the exact two-step scratchpad path:

  1. crop to the paper (Otsu largest-bright-component bbox, 3% inset), the same
     logic as crop_page.py, written to <stem>_cropped.jpg as JPEG and re-read
     (the JPEG round-trip is part of the original path and is preserved).
  2. flat-field the gray paper cast (25x25 grayscale morphological close as the
     illumination estimate, divide), deskew, then segment lines by BLIND
     autocorrelation pitch + peak detection (robust to the raised inter-line
     valley floor that defeats decode.py's fixed 0.10*max threshold on real
     blurred captures), then score with decode.py's own line_baseline and
     subpixel_gaps. Sign decisions only, identical to decode.py.

decode.py itself is NOT modified. This wrapper reuses its functions. Merging
this segmentation into decode.py is a separate, deliberate step (see the repo
handoff / open items), not done here.

IMPORTANT for the control run: shoot the unmarked control at MATCHED framing and
tilt to the marked capture, then decode it against the MARKED meta:
  python robust_decode/run_robust.py --img control_received.jpeg --meta meta.json
It must score near 0.5 on line-shift. If it scores high, the pipeline is reading
layout, not embedded signal, and the 0.933 is meaningless.

Usage:
  python robust_decode/run_robust.py --img received.jpeg --meta meta.json
  # defaults reproduce the recorded result:
  python robust_decode/run_robust.py
"""
import argparse, json, os, sys

import cv2
import numpy as np

# Make decode.py (repo root) importable regardless of where the repo lives.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from decode import deskew, line_baseline, subpixel_gaps  # noqa: E402


def crop_to_page(src, dst, verbose=True):
    """Otsu largest-bright-component bbox with a 3% inset. Same as crop_page.py.
    Writes the crop to dst as JPEG and returns the path (round-trip preserved)."""
    img = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
    b = cv2.GaussianBlur(img, (0, 0), 3)
    _, m = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, _, stats, _ = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8), 8)
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (stats[k, cv2.CC_STAT_LEFT], stats[k, cv2.CC_STAT_TOP],
                  stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT])
    ix, iy = int(w * 0.03), int(h * 0.03)
    x0, y0 = max(0, x + ix), max(0, y + iy)
    x1, y1 = min(img.shape[1], x + w - ix), min(img.shape[0], y + h - iy)
    crop = cv2.imread(src, cv2.IMREAD_COLOR)[y0:y1, x0:x1]
    cv2.imwrite(dst, crop)
    if verbose:
        print(f"crop: page bbox ({x},{y},{w},{h}) -> {x1 - x0}x{y1 - y0} -> {dst}")
    return dst


PITCH_FLOOR = 24    # autocorr search floor, px. Must sit below the smallest real
                    # line pitch or argmax locks onto the 2x harmonic and finds
                    # half the lines. The marked capture is ~30 px, the control
                    # ~26 px; a floor of 30 broke the control (found 22/45).


def segment_autocorr(gray):
    """Blind line bands via autocorrelation pitch + peak detection, midpoint
    boundaries. Returns list of (top, bottom) bands."""
    ink = 255.0 - gray.astype(np.float64)
    prof = np.convolve(ink.sum(axis=1), np.ones(3) / 3, mode="same")
    p = prof - prof.mean()
    ac = np.correlate(p, p, mode="full")[len(p) - 1:]
    pitch = PITCH_FLOOR + int(np.argmax(ac[PITCH_FLOOR:120]))
    mind = int(0.6 * pitch)
    cand = [i for i in range(1, len(prof) - 1)
            if prof[i] >= prof[i - 1] and prof[i] > prof[i + 1]
            and prof[i] > prof.mean()]
    peaks = []
    for i in sorted(cand, key=lambda x: -prof[x]):
        if all(abs(i - j) >= mind for j in peaks):
            peaks.append(i)
    peaks = sorted(peaks)
    # Trim boundary artifacts: a peak at the crop edge separated from the text
    # block by an abnormally large gap (page edge or shadow, not a text line).
    # The loose Otsu crop on a low-contrast background can leave one; the control
    # had a spurious peak at row 2 with a 122 px gap to the first real line.
    if len(peaks) >= 3:
        med = float(np.median(np.diff(peaks)))
        while len(peaks) >= 3 and (peaks[1] - peaks[0]) > 1.8 * med:
            peaks.pop(0)
        while len(peaks) >= 3 and (peaks[-1] - peaks[-2]) > 1.8 * med:
            peaks.pop()
    bnds = [0] + [(peaks[i] + peaks[i + 1]) // 2 for i in range(len(peaks) - 1)] \
        + [gray.shape[0]]
    return [(bnds[i], bnds[i + 1]) for i in range(len(peaks))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default="received.jpeg",
                    help="raw capture (default reproduces the recorded 0.933)")
    ap.add_argument("--meta", default="meta.json",
                    help="MARKED meta for scoring (use meta.json for controls too)")
    args = ap.parse_args()

    meta = json.load(open(args.meta))
    stem = os.path.splitext(os.path.basename(args.img))[0]
    cropped = crop_to_page(args.img, f"{stem}_cropped.jpg")

    gray0 = cv2.imread(cropped, cv2.IMREAD_GRAYSCALE)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    bg = cv2.morphologyEx(gray0, cv2.MORPH_CLOSE, kern)
    norm = np.clip(gray0.astype(np.float64) / np.maximum(bg, 1) * 255, 0, 255) \
        .astype(np.uint8)
    gray, ang = deskew(norm)
    bands = segment_autocorr(gray)
    print(f"deskew {ang:+.2f}, {len(bands)} lines found, {meta['n_lines']} expected")
    if len(bands) != meta["n_lines"]:
        print("LINE COUNT MISMATCH: segmentation failed, aborting scoring.")
        return

    baselines = [line_baseline(gray, a, b) for a, b in bands]

    # line-shift, identical to decode.py
    l_ok = l_tot = 0
    for t in range(meta["n_lines"] // 3):
        i = 3 * t + 1
        bp, bm, bn = baselines[i - 1], baselines[i], baselines[i + 1]
        truth = meta["lines"][i]["line_bit"]
        if None in (bp, bm, bn) or truth is None:
            continue
        stat = (bm - bp) - (bn - bm)
        l_tot += 1
        l_ok += int((1 if stat > 0 else 0) == truth)

    # word-shift, identical to decode.py
    w_ok = w_tot = w_erase = 0
    votes = {}
    slot = 0
    payload = meta["payload"]
    for li, (a, b) in enumerate(bands):
        info = meta["lines"][li]
        nw = info["n_words"]
        slots = [i for i in range(1, nw - 1) if i % 2 == 1]
        widths = subpixel_gaps(gray, a, b, nw)
        if widths is None:
            w_erase += len(slots)
            slot += len(slots)
            continue
        for widx, raw in zip(slots, [(widths[j - 1] - widths[j]) for j in slots]):
            truth = info["word_bits"][widx]
            bit = 1 if raw > 0 else 0
            if truth is not None:
                w_tot += 1
                w_ok += int(bit == truth)
                votes.setdefault(slot % len(payload), []).append(bit)
            slot += 1

    pay_ok = sum(1 for pp, v in votes.items()
                 if int(np.mean(v) > 0.5) == payload[pp])
    la = l_ok / l_tot if l_tot else float("nan")
    wa = w_ok / w_tot if w_tot else float("nan")
    print(f"line-shift : {l_ok}/{l_tot} = {la:.3f} raw bit accuracy")
    print(f"word-shift : {w_ok}/{w_tot} = {wa:.3f} raw bit accuracy "
          f"({w_erase} erasures)")
    print(f"payload    : {pay_ok}/{len(votes)} bits after repetition vote")
    go = (wa >= 0.85) or (la >= 0.90)
    print(f"GO/NO-GO   : {'GO' if go else 'NO-GO'} (word>=0.85 or line>=0.90; "
          f"UNVALIDATED until the unmarked control scores ~0.5 here)")


if __name__ == "__main__":
    main()
