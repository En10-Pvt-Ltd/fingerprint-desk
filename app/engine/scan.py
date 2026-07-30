# SPDX-License-Identifier: Apache-2.0
"""Scan a leaked image against every variant of a test and attribute it.

Reuses the research decoders directly, no reimplementation:
  decode.py       deskew, segment_lines, line_baseline, subpixel_gaps
  run_robust.py   crop_to_page, segment_autocorr (real-capture path)

Observations (baseline second-differences per triplet, adjacent-gap
differentials per word slot) are meta-independent; they are extracted once
and then scored against every marked variant's ground-truth bits. Controls
are rendered for printing and for the credibility story, but carry no truth
bits, so the score table lists marked variants only; a scan OF a control
print must read near chance against all of them.

Attribution rule (stated on every result): claim only when the best
variant's exact binomial p-value against chance, Bonferroni-corrected for
the number of variants tested, is at most P_THRESHOLD and at least MIN_BITS
symbols were observed. Otherwise the verdict is "no attribution".
"""
import json
import math
import os

import cv2
import numpy as np

from . import REPO  # noqa: F401  (sys.path side effect)
import decode as dec
import encode
from run_robust import crop_to_page, segment_autocorr
from . import store
from .render import load_page_meta

P_THRESHOLD = 1e-3
MIN_BITS = 10
# Separation (margin) rule: the top candidate must beat the runner-up by
# max(MARGIN_MIN_BITS, MARGIN_MIN_FRAC * observed bits) agreed bits. The
# relative term guards long reads (a 2-bit lead over 51 bits is noise);
# the absolute term guards short reads (8% of 15 bits is under one bit).
# At ~50 bits the two coincide (4 bits ~ 8%). Both wrong-variant cases in
# the 300-variant simulation had 1-2 bit leads and are rejected; a clean
# capture (agreement ~0.95 vs runner-up ~0.55) clears it by a wide gap.
MARGIN_MIN_FRAC = 0.08
MARGIN_MIN_BITS = 4

MARGIN_RULE_TEXT = (f"top candidate beats runner-up by >= "
                    f"max({MARGIN_MIN_BITS} bits, "
                    f"{MARGIN_MIN_FRAC:.0%} of observed bits)")


def binom_p(ok, tot):
    """Exact one-sided binomial tail P(X >= ok | n=tot, p=0.5).

    Big-int numerator and denominator: Python's int/int true division is
    correctly rounded at any size, so this stays finite past 1023 bits
    (pooled multi-photo totals) where 2.0 ** tot would overflow."""
    if tot <= 0:
        return None
    return sum(math.comb(tot, k) for k in range(ok, tot + 1)) / (1 << tot)


def margin_check(top, second):
    """Does the top candidate clearly beat the runner-up?

    top/second are score rows with "ok"/"tot". Returns
    (passed, gap_bits, needed_bits). No runner-up (single-variant test)
    passes trivially; the gap is measured in bits on the top candidate's
    scale so unequal tots compare fairly."""
    if second is None or not second.get("tot"):
        return True, None, None
    if not top.get("tot"):
        return False, None, None
    gap = top["ok"] - second["ok"] * top["tot"] / second["tot"]
    need = max(MARGIN_MIN_BITS, MARGIN_MIN_FRAC * top["tot"])
    return gap >= need, round(gap, 2), round(need, 2)


def prep_clean(gray):
    g, ang = dec.deskew(gray)
    return g, dec.segment_lines(g), ang, "clean"


def prep_robust(img_path, workdir):
    """The run_robust.py path: crop -> flat-field -> deskew -> autocorr."""
    cropped = crop_to_page(img_path, os.path.join(workdir, "cropped.jpg"),
                           verbose=False)
    g0 = cv2.imread(cropped, cv2.IMREAD_GRAYSCALE)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    bg = cv2.morphologyEx(g0, cv2.MORPH_CLOSE, kern)
    norm = np.clip(g0.astype(np.float64) / np.maximum(bg, 1) * 255,
                   0, 255).astype(np.uint8)
    g, ang = dec.deskew(norm)
    return g, segment_autocorr(g), ang, "robust"


def observe(gray, bands, ref_line_words):
    """Meta-independent observations for one candidate page layout."""
    baselines = [dec.line_baseline(gray, a, b) for a, b in bands]
    line_obs = []
    for t in range(len(bands) // 3):
        i = 3 * t + 1
        bp, bm, bn = baselines[i - 1], baselines[i], baselines[i + 1]
        if None in (bp, bm, bn):
            line_obs.append(None)
        else:
            line_obs.append(1 if (bm - bp) - (bn - bm) > 0 else 0)
    word_obs = []
    for li, (a, b) in enumerate(bands):
        nw = ref_line_words[li]
        widths = dec.subpixel_gaps(gray, a, b, nw) if nw >= 3 else None
        if widths is None:
            word_obs.append(None)
        else:
            word_obs.append({j: (1 if widths[j - 1] - widths[j] > 0 else 0)
                             for j in encode.slot_indices(nw)})
    return line_obs, word_obs


def score_meta(line_obs, word_obs, meta):
    l_ok = l_tot = 0
    for t, ob in enumerate(line_obs):
        i = 3 * t + 1
        truth = meta["lines"][i]["line_bit"] if i < len(meta["lines"]) else None
        if ob is not None and truth is not None:
            l_tot += 1
            l_ok += int(ob == truth)
    w_ok = w_tot = 0
    for li, obs in enumerate(word_obs):
        if not obs or li >= len(meta["lines"]):
            continue
        wb = meta["lines"][li]["word_bits"]
        for j, bit in obs.items():
            truth = wb[j] if j < len(wb) else None
            if truth is not None:
                w_tot += 1
                w_ok += int(bit == truth)
    ok, tot = l_ok + w_ok, l_tot + w_tot
    return {"line_ok": l_ok, "line_tot": l_tot,
            "line_acc": round(l_ok / l_tot, 3) if l_tot else None,
            "word_ok": w_ok, "word_tot": w_tot,
            "word_acc": round(w_ok / w_tot, 3) if w_tot else None,
            "ok": ok, "tot": tot,
            "acc": round(ok / tot, 3) if tot else None,
            "p_value": binom_p(ok, tot)}


def attribute(manifest, img_path, workdir, source, only_pages=None):
    """Run the full scan. Returns the result dict (also written to
    workdir/result.json by the caller). only_pages restricts which page
    indices may match (used by the self-verify guard; None = any page)."""
    test_id = manifest["test_id"]
    marked = [d for d in manifest["docs"] if d["marked"]]
    page_nlines = {p["page_index"]: p["n_lines"] for p in marked[0]["pages"]
                   if only_pages is None or p["page_index"] in only_pages}

    gray = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return {"error": "could not read image"}

    result = {"test_id": test_id, "source": source,
              "timestamp": store.now_utc(),
              "attribution_rule": {"p_threshold": P_THRESHOLD,
                                   "min_bits": MIN_BITS,
                                   "correction": "bonferroni x n_variants",
                                   "margin": MARGIN_RULE_TEXT}}

    g, bands, ang, path_used = prep_clean(gray)
    candidates = [k for k, n in page_nlines.items() if n == len(bands)]
    if not candidates:
        g, bands, ang, path_used = prep_robust(img_path, workdir)
        candidates = [k for k, n in page_nlines.items() if n == len(bands)]
    result.update({"path_used": path_used, "deskew_deg": round(ang, 2),
                   "n_lines_found": len(bands)})
    if not candidates:
        exp = sorted(set(page_nlines.values()))
        lo, hi = min(exp), max(exp)
        if len(bands) < lo:
            reason = "partial framing: text cut off"
            note = (f"Only {len(bands)} text lines were found; the smallest "
                    f"page of this test has {lo}. The photo most likely cuts "
                    "off part of the text block (with short content the text "
                    "sits in the top part of the sheet). Retake with the "
                    "whole printed text inside the frame.")
        elif len(bands) > hi:
            reason = "rotation or background clutter"
            note = (f"{len(bands)} line-like structures were found; the "
                    f"largest page of this test has {hi}. This usually means "
                    "the page is strongly rotated in the photo (the blind "
                    "deskew corrects only a few degrees) or the frame "
                    "contains busy background. Keep the page roughly upright "
                    "and fill the frame with the paper.")
        else:
            reason = "line count mismatch"
            note = (f"Found {len(bands)} lines, which matches no page of "
                    f"this test (pages have {exp}). Check that the capture "
                    "shows one full page from this test.")
        result.update({"verdict": {"attributed": False, "reason": reason},
                       "note": note})
        return result

    best_page, page_scores = None, {}
    for k in candidates:
        ref_meta = load_page_meta(test_id, marked[0]["doc_id"], k)
        ref_line_words = [l["n_words"] for l in ref_meta["lines"]]
        line_obs, word_obs = observe(g, bands, ref_line_words)
        rows = []
        for d in marked:
            meta = load_page_meta(test_id, d["doc_id"], k)
            sc = score_meta(line_obs, word_obs, meta)
            sc.update({"doc_id": d["doc_id"], "label": d["label"]})
            rows.append(sc)
        rows.sort(key=lambda r: (r["acc"] or 0), reverse=True)
        page_scores[k] = rows
        top = rows[0]["acc"] or 0
        if best_page is None or top > (page_scores[best_page][0]["acc"] or 0):
            best_page = k

    rows = page_scores[best_page]
    n_var = len(marked)
    for r in rows:
        r["p_adj"] = min(1.0, r["p_value"] * n_var) \
            if r["p_value"] is not None else None
    best, second = rows[0], (rows[1] if len(rows) > 1 else None)
    evid_ok = (best["p_adj"] is not None and best["p_adj"] <= P_THRESHOLD
               and best["tot"] >= MIN_BITS)
    sep_ok, gap_bits, need_bits = margin_check(best, second)
    attributed = evid_ok and sep_ok
    result.update({
        "page_index": best_page,
        "scores": rows,
        "verdict": {
            "attributed": attributed,
            "doc_id": best["doc_id"] if attributed else None,
            "label": best["label"] if attributed else None,
            "acc": best["acc"], "tot": best["tot"],
            "p_value": best["p_value"], "p_adj": best["p_adj"],
            "margin": round((best["acc"] or 0) - (second["acc"] or 0), 3)
            if second else None,
            "margin_bits": gap_bits, "margin_needed": need_bits,
            "reason": "ok" if attributed
            else ("runner-up too close" if evid_ok
                  else "below evidence threshold"),
        }})
    if not attributed:
        if evid_ok:
            result["note"] = ("Two copies match too closely at this photo "
                              "quality to tell apart, so no attribution is "
                              "claimed. A sharper photo, or photos of the "
                              "other pages, should separate them.")
        else:
            result["note"] = ("No variant separates from chance at the "
                              "stated threshold. Expected when scanning an "
                              "unmarked control, a document from another "
                              "test, or a capture too degraded to read.")
    return result


def pooled_verdict(results):
    """One contributor's combined verdict across all their real-photo scans
    of a test.

    Per-candidate bit agreements (each scan result's score rows carry
    ok/tot per candidate doc) are pooled across pages and the exact same
    rule as a single scan is applied to the totals: Bonferroni-corrected
    exact binomial p <= P_THRESHOLD, at least MIN_BITS observed, and
    margin_check against the runner-up.

    Photos of the *same* page re-observe the same physical bits, so they
    are correlated evidence, not independent -- summing them would let
    repeated uploads of one marginal page walk a control past the
    threshold. Only the best-read photo (most observed bits) per
    identified page contributes; scans whose page could not be identified
    (page_index None) conservatively share a single slot. Photos of
    different pages simply add their bits.

    Returns None when no scan carries scores. Works for both the rendered
    and the formatting-preserved (PDF) carrier: score rows share the
    ok/tot shape."""
    best_per_page, n_photos = {}, 0
    for r in results or []:
        rows = r.get("scores")
        if not rows:
            continue
        n_photos += 1
        bits = sum(s["tot"] or 0 for s in rows)
        key = r.get("page_index")
        cur = best_per_page.get(key)
        if cur is None or bits > cur[0]:
            best_per_page[key] = (bits, rows)
    agg = {}
    for _, rows in best_per_page.values():
        for s in rows:
            a = agg.setdefault(s["doc_id"], {"doc_id": s["doc_id"],
                                             "label": s["label"],
                                             "ok": 0, "tot": 0})
            a["ok"] += s["ok"] or 0
            a["tot"] += s["tot"] or 0
    if not agg:
        return None
    rows = sorted(agg.values(),
                  key=lambda a: (a["ok"] / a["tot"]) if a["tot"] else 0,
                  reverse=True)
    n_var = len(rows)
    for a in rows:
        a["acc"] = round(a["ok"] / a["tot"], 3) if a["tot"] else None
        p = binom_p(a["ok"], a["tot"])
        a["p_value"] = p
        a["p_adj"] = min(1.0, p * n_var) if p is not None else None
    top, second = rows[0], (rows[1] if len(rows) > 1 else None)
    evid_ok = (top["p_adj"] is not None and top["p_adj"] <= P_THRESHOLD
               and top["tot"] >= MIN_BITS)
    sep_ok, gap_bits, need_bits = margin_check(top, second)
    attributed = evid_ok and sep_ok
    reason = None
    if not attributed:
        if top["tot"] < MIN_BITS:
            reason = (f"only {top['tot']} marks were readable across your "
                      f"photos (at least {MIN_BITS} are needed); a photo of "
                      "another page will add more")
        elif not evid_ok:
            reason = ("across your photos, no copy separates from chance -- "
                      "expected for a control print or captures too "
                      "degraded to read")
        else:
            reason = ("two copies match too closely at this photo quality; "
                      "a photo of another page should separate them")
    return {"attributed": attributed,
            "attributed_doc": top["doc_id"] if attributed else None,
            "label": top["label"] if attributed else None,
            "agreement": top["acc"], "n_bits": top["tot"],
            "n_photos": n_photos, "n_pages_used": len(best_per_page),
            "p_adj": top["p_adj"],
            "margin_bits": gap_bits, "margin_needed": need_bits,
            "abstain_reason": reason}


def run_scan(manifest, img_path, source, scan_pair=None):
    """Create (or reuse) the scan record folder, run attribution, persist
    result.json."""
    scan_id, sdir = scan_pair or store.new_scan_dir(manifest["test_id"])
    result = attribute(manifest, img_path, sdir, source)
    result["scan_id"] = scan_id
    with open(os.path.join(sdir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    return result
