#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Blind smoke-test decoder for Carrier 1 (word-shift + line-shift).

Blind means: no fiducials, no access to the original image, geometry recovered
from text baselines only. The decoder knows the public encoding convention
(triplet structure, interior-word slots, sign convention). The sidecar meta
JSON is used ONLY to score the blind decode against ground truth.

Pipeline: grayscale -> deskew (profile-variance search) -> line segmentation
(row-profile runs) -> per-line baseline (median of component bottoms) ->
line-shift bits from baseline-spacing differentials -> per-line column profile
-> subpixel gap widths (threshold-crossing interpolation) -> word-shift bits
from adjacent-gap differentials. Sign decisions only, so the decoder is
scale-free.

Usage:
  python decode.py --img captured.jpg --meta meta.json
"""
import argparse, json
import numpy as np
import cv2


def deskew(gray):
    small = cv2.resize(gray, (1000, int(1000 * gray.shape[0] / gray.shape[1])),
                       interpolation=cv2.INTER_AREA)
    ink = 255 - small
    best_a, best_v = 0.0, -1.0
    for a in np.arange(-3.0, 3.001, 0.05):
        M = cv2.getRotationMatrix2D((small.shape[1] / 2, small.shape[0] / 2),
                                    a, 1.0)
        r = cv2.warpAffine(ink, M, (small.shape[1], small.shape[0]))
        v = float(np.var(r.sum(axis=1)))
        if v > best_v:
            best_v, best_a = v, a
    M = cv2.getRotationMatrix2D((gray.shape[1] / 2, gray.shape[0] / 2),
                                best_a, 1.0)
    return cv2.warpAffine(gray, M, (gray.shape[1], gray.shape[0]),
                          flags=cv2.INTER_LINEAR, borderValue=255), best_a


def segment_lines(gray):
    ink = (255.0 - gray.astype(np.float64))
    prof = ink.sum(axis=1)
    prof = np.convolve(prof, np.ones(3) / 3, mode="same")
    thr = 0.10 * prof.max()
    on = prof > thr
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
        return []
    med_h = np.median([b - a for a, b in runs])
    # Merge runs separated by a small gap (broken lines), drop specks.
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] < 0.35 * med_h:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    med_h = np.median([b - a for a, b in merged])
    return [(a, b) for a, b in merged if (b - a) > 0.4 * med_h]


def line_baseline(gray, a, b):
    """Baseline = robust location of character bottoms in band [a,b)."""
    pad = max(2, (b - a) // 4)
    y0, y1 = max(0, a - pad), min(gray.shape[0], b + pad)
    band = gray[y0:y1]
    binv = (band < 128).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(binv, connectivity=8)
    if n <= 1:
        return None
    hs = stats[1:, cv2.CC_STAT_HEIGHT]
    med_h = np.median(hs)
    bottoms = []
    for i in range(1, n):
        h = stats[i, cv2.CC_STAT_HEIGHT]
        w = stats[i, cv2.CC_STAT_WIDTH]
        if h >= 0.55 * med_h and w >= 2:      # drop dots, commas
            bottoms.append(stats[i, cv2.CC_STAT_TOP] + h)
    if len(bottoms) < 3:
        return None
    bottoms = np.array(bottoms, dtype=np.float64)
    med = np.median(bottoms)
    core = bottoms[np.abs(bottoms - med) <= 0.18 * med_h + 1.0]  # exclude descenders
    return y0 + (core.mean() if len(core) else med)


def subpixel_gaps(gray, a, b, expected_words, rel_gap_min=0.25):
    """Return subpixel widths of the expected_words-1 largest gaps, in order."""
    pad = 2
    y0, y1 = max(0, a - pad), min(gray.shape[0], b + pad)
    band = 255.0 - gray[y0:y1].astype(np.float64)
    prof = band.sum(axis=0)
    prof = np.convolve(prof, np.ones(2) / 2, mode="same")
    thr = 0.06 * np.percentile(prof, 95)
    # Trim leading/trailing whitespace.
    onc = np.where(prof > thr)[0]
    if len(onc) < 10:
        return None
    lo, hi = onc[0], onc[-1]
    p = prof[lo:hi + 1]
    below = p < thr
    # Candidate gaps: runs below threshold.
    gaps, start = [], None
    for i, v in enumerate(below):
        if v and start is None:
            start = i
        elif not v and start is not None:
            gaps.append((start, i))
            start = None
    if start is not None:
        gaps.append((start, len(below)))
    if len(gaps) < expected_words - 1:
        return None
    # Keep the expected_words-1 widest, restore document order.
    gaps = sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)[:expected_words - 1]
    gaps = sorted(gaps, key=lambda g: g[0])
    widths = []
    for s, e in gaps:
        # Subpixel edges by linear interpolation of the threshold crossing.
        ls = float(s)
        if s > 0 and p[s - 1] != p[s]:
            ls = (s - 1) + (p[s - 1] - thr) / (p[s - 1] - p[s])
        re = float(e)
        if e < len(p) and p[e] != p[e - 1]:
            re = (e - 1) + (p[e - 1] - thr) / (p[e - 1] - p[e])
        widths.append(re - ls)
    return widths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--json", default=None, help="optional results JSON path")
    args = ap.parse_args()
    meta = json.load(open(args.meta))

    gray = cv2.imread(args.img, cv2.IMREAD_GRAYSCALE)
    gray, angle = deskew(gray)
    bands = segment_lines(gray)
    print(f"deskew {angle:+.2f} deg, {len(bands)} lines found, "
          f"{meta['n_lines']} expected")
    if len(bands) != meta["n_lines"]:
        print("LINE COUNT MISMATCH: segmentation failed, aborting scoring. "
              "Inspect thresholds or capture quality.")
        return

    baselines = [line_baseline(gray, a, b) for a, b in bands]

    # Line-shift decode: triplets (control, marked, control).
    l_ok = l_tot = 0
    for t in range(meta["n_lines"] // 3):
        i = 3 * t + 1
        b_prev, b_m, b_next = baselines[i - 1], baselines[i], baselines[i + 1]
        truth = meta["lines"][i]["line_bit"]
        if None in (b_prev, b_m, b_next) or truth is None:
            continue
        stat = (b_m - b_prev) - (b_next - b_m)   # = 2*shift, + means down
        bit = 1 if stat > 0 else 0
        l_tot += 1
        l_ok += int(bit == truth)

    # Word-shift decode.
    w_ok = w_tot = w_erase = 0
    votes = {}                                   # payload-position majority vote
    slot = 0
    payload = meta["payload"]
    for li, (a, b) in enumerate(bands):
        info = meta["lines"][li]
        nw = info["n_words"]
        slots = [i for i in range(1, nw - 1) if i % 2 == 1]  # public convention
        widths = subpixel_gaps(gray, a, b, nw)
        if widths is None:
            w_erase += len(slots)
            slot += len(slots)
            continue
        stats = [(widths[j - 1] - widths[j]) for j in slots]
        # No per-line median correction: nominal gaps are uniform by
        # construction, and a median subtract would zero out lines whose
        # slot bits happen to all agree.
        for widx, raw in zip(slots, stats):
            truth = info["word_bits"][widx]
            bit = 1 if raw > 0 else 0
            if truth is not None:
                w_tot += 1
                w_ok += int(bit == truth)
                pp = slot % len(payload)
                votes.setdefault(pp, []).append(bit)
            slot += 1

    pay_ok = sum(1 for pp, v in votes.items()
                 if int(np.mean(v) > 0.5) == payload[pp])
    pay_tot = len(votes)

    line_acc = l_ok / l_tot if l_tot else float("nan")
    word_acc = w_ok / w_tot if w_tot else float("nan")
    print(f"line-shift : {l_ok}/{l_tot} = {line_acc:.3f} raw bit accuracy")
    print(f"word-shift : {w_ok}/{w_tot} = {word_acc:.3f} raw bit accuracy "
          f"({w_erase} erasures)")
    print(f"payload    : {pay_ok}/{pay_tot} bits after repetition vote")
    go = (word_acc >= 0.85) or (line_acc >= 0.90)
    print(f"GO/NO-GO   : {'GO' if go else 'NO-GO'} "
          f"(GO if word>=0.85 or line>=0.90 on REAL captures; "
          f"synthetic runs are sanity checks only)")
    if args.json:
        json.dump({"line_acc": line_acc, "word_acc": word_acc,
                   "erasures": w_erase, "payload_ok": pay_ok,
                   "payload_tot": pay_tot, "deskew_deg": angle},
                  open(args.json, "w"))


if __name__ == "__main__":
    main()
