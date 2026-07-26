#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fragment-capable Carrier 1 decoder for the corpus harness.

Generalizes robust_decode/run_robust.py (the validated real-capture pipeline)
to (a) tolerate line-count mismatch by aligning a detected line block to a
contiguous window of the ground-truth layout, and (b) return per-Tardos-position
signed LLRs so the harness can score soft (via k_eff) and hard (flip) and fuse
with Carrier 2.

It scores THROUGH the robust pipeline (crop -> flat-field -> autocorrelation
segmentation with PITCH_FLOOR + boundary trimming, from run_robust). It never
calls decode.py's own segmentation, which is full-page-synthetic only and fails
on real captures. It does reuse decode.py's per-line primitives (deskew,
line_baseline, subpixel_gaps), which are sound.

LLR CALIBRATION CAVEAT: per-observation confidences are a heuristic monotone map
of the shift-differential magnitude normalized by a per-page robust scale. They
are UNCALIBRATED placeholders (consistent with metrics.py's "cells are
placeholders" stance). The interface (signed per-position LLRs) and the dual
scoring are the deliverable; the constant is fixed later against the corpus.

decode_c1(img_path, truth_meta) returns a dict with, over payload positions:
  decoded : list[int]  1/0 decided bit, -1 = erasure (position unobserved)
  truth   : list[int]  ground-truth payload bit at that position
  llrs    : list[float] signed accumulated LLR (sign = belief, |.| = confidence)
plus diagnostics (n_found, n_expected, offset, line_acc, word_acc, n_obs).

Fragment alignment is IMPLEMENTED but UNVALIDATED: no partial-page real capture
exists yet. Full-page captures take the identity offset and reproduce
run_robust's numbers exactly.
"""
import os
import sys
import tempfile

import cv2
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decode import deskew, line_baseline, subpixel_gaps            # noqa: E402
from run_robust import crop_to_page, segment_autocorr             # noqa: E402

LLR_GAIN = 2.0        # heuristic: scale of |normalized differential| -> LLR
LLR_MAX = 4.0         # clamp per-observation LLR magnitude


def _prep(img_path):
    """crop -> flat-field -> deskew. Returns the deskewed grayscale page."""
    tmp = os.path.join(tempfile.gettempdir(),
                       f"c1_{os.path.basename(img_path)}.crop.jpg")
    cropped = crop_to_page(img_path, tmp, verbose=False)
    gray0 = cv2.imread(cropped, cv2.IMREAD_GRAYSCALE)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    bg = cv2.morphologyEx(gray0, cv2.MORPH_CLOSE, kern)
    norm = np.clip(gray0.astype(np.float64) / np.maximum(bg, 1) * 255, 0, 255) \
        .astype(np.uint8)
    gray, _ = deskew(norm)
    return gray


def _detected_word_counts(gray, bands):
    """Rough words-per-band via profile-gap counting. Used only for fragment
    alignment; deliberately relaxed (exact counts are unreliable on blur)."""
    out = []
    for a, b in bands:
        y0, y1 = max(0, a - 2), min(gray.shape[0], b + 2)
        prof = (255.0 - gray[y0:y1].astype(np.float64)).sum(axis=0)
        prof = np.convolve(prof, np.ones(2) / 2, mode="same")
        thr = 0.06 * np.percentile(prof, 95)
        on = prof > thr
        gaps = np.sum((~on[1:]) & on[:-1])       # rising edges ~ word starts
        out.append(int(gaps) + 1)
    return out


def _align_offset(gray, bands, meta):
    """Best contiguous offset mapping detected bands onto meta lines.

    Full page (n_found >= n_lines): identity offset 0. Fragment (n_found <
    n_lines): slide the detected word-count signature over the meta n_words
    signature and pick the min-L1 offset. Unvalidated until fragment captures
    exist; full-page path never depends on the word-count estimate."""
    n_exp = meta["n_lines"]
    m = len(bands)
    if m >= n_exp:
        return 0
    obs = _detected_word_counts(gray, bands)
    meta_wc = [ln["n_words"] for ln in meta["lines"]]
    best = (float("inf"), 0)
    for o in range(0, n_exp - m + 1):
        cost = sum(abs(obs[i] - meta_wc[o + i]) for i in range(m))
        if cost < best[0]:
            best = (cost, o)
    return best[1]


def _word_slot_base(meta):
    """Cumulative interior-odd word-slot count before each line, so a fragment
    can compute the correct global payload position for its words."""
    base, cum = [], 0
    for ln in meta["lines"]:
        base.append(cum)
        nw = ln["n_words"]
        cum += len([i for i in range(1, nw - 1) if i % 2 == 1])
    return base


def _confidences(stats):
    """Heuristic per-observation LLR magnitudes from a list of signed stats,
    normalized by the page's robust scale. Returns (scale, list_of_conf)."""
    a = np.abs(np.array([s for s in stats if s is not None], dtype=np.float64))
    scale = float(np.median(a)) if len(a) else 1.0
    scale = scale if scale > 1e-9 else 1.0
    return scale


def decode_c1(img_path, truth_meta):
    """Decode a capture through the robust pipeline against truth_meta.
    Returns per-payload-position decoded/truth/llrs plus diagnostics."""
    gray = _prep(img_path)
    bands = segment_autocorr(gray)
    n_found, n_exp = len(bands), truth_meta["n_lines"]
    offset = _align_offset(gray, bands, truth_meta)

    # Map detected band index -> meta line index, keep only in-range.
    band_to_meta = {}
    for li_local in range(min(n_found, n_exp - offset)):
        band_to_meta[li_local] = offset + li_local

    payload = truth_meta["payload"]
    P = len(payload)
    baselines = {}                      # meta_line_index -> baseline y
    for li_local, mi in band_to_meta.items():
        baselines[mi] = line_baseline(gray, *bands[li_local])

    # ---- collect line-shift observations (per triplet) ----
    line_obs = []                       # (payload_pos, signed_stat, truth_bit)
    for t in range(n_exp // 3):
        i0, i1, i2 = 3 * t, 3 * t + 1, 3 * t + 2
        if not all(k in baselines and baselines[k] is not None
                   for k in (i0, i1, i2)):
            continue
        truth = truth_meta["lines"][i1]["line_bit"]
        if truth is None:               # unmarked meta: no line truth here
            truth = payload[t % P]      # score control vs a marked codeword
        stat = (baselines[i1] - baselines[i0]) - (baselines[i2] - baselines[i1])
        line_obs.append((t % P, stat, truth))

    # ---- collect word-shift observations ----
    slot_base = _word_slot_base(truth_meta)
    word_obs = []
    for li_local, mi in band_to_meta.items():
        info = truth_meta["lines"][mi]
        nw = info["n_words"]
        slots = [i for i in range(1, nw - 1) if i % 2 == 1]
        widths = subpixel_gaps(gray, *bands[li_local], nw)
        if widths is None:
            continue                    # erasure: gaps unresolved at this res
        for k, widx in enumerate(slots):
            stat = widths[widx - 1] - widths[widx]
            gpos = (slot_base[mi] + k) % P
            truth = info["word_bits"][widx]
            if truth is None:
                truth = payload[gpos]
            word_obs.append((gpos, stat, truth))

    # ---- per-observation LLRs, normalized by per-carrier robust scale ----
    llr = [0.0] * P
    obs_count = [0] * P
    truth_vec = list(payload)
    for obs in (line_obs, word_obs):
        scale = _confidences([s for _, s, _ in obs])
        for pp, stat, truth in obs:
            conf = min(LLR_MAX, LLR_GAIN * abs(stat) / scale)
            bit = 1 if stat > 0 else 0
            llr[pp] += conf if bit == 1 else -conf
            obs_count[pp] += 1
            truth_vec[pp] = truth

    decoded = [(-1 if obs_count[pp] == 0 else (1 if llr[pp] > 0 else 0))
               for pp in range(P)]

    # ---- diagnostics: raw carrier accuracies (as run_robust reports) ----
    def raw_acc(obs):
        ok = tot = 0
        for pp, stat, truth in obs:
            tot += 1
            ok += int((1 if stat > 0 else 0) == truth)
        return (ok, tot)
    l_ok, l_tot = raw_acc(line_obs)
    w_ok, w_tot = raw_acc(word_obs)

    return {
        "decoded": decoded, "truth": truth_vec, "llrs": llr,
        "n_found": n_found, "n_expected": n_exp, "offset": offset,
        "n_obs": sum(1 for d in decoded if d >= 0),
        "line_acc": (l_ok / l_tot) if l_tot else float("nan"),
        "word_acc": (w_ok / w_tot) if w_tot else float("nan"),
        "line_bits": (l_ok, l_tot), "word_bits": (w_ok, w_tot),
    }


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="c1 fragment-capable decode")
    ap.add_argument("--img", required=True)
    ap.add_argument("--meta", required=True)
    args = ap.parse_args()
    r = decode_c1(args.img, json.load(open(args.meta)))
    print(f"lines found {r['n_found']}/{r['n_expected']} offset {r['offset']}")
    print(f"line-shift {r['line_bits'][0]}/{r['line_bits'][1]} = "
          f"{r['line_acc']:.3f} | word-shift {r['word_bits'][0]}/"
          f"{r['word_bits'][1]} = {r['word_acc']:.3f}")
    print(f"positions observed {r['n_obs']}/{len(r['decoded'])}")
