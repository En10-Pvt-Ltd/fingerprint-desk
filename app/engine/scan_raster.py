# SPDX-License-Identifier: Apache-2.0
"""Attribution for raster (image-only PDF) tests.

Same product semantics as scan_pdf.attribute (Bonferroni-corrected exact
binomial threshold, margin rule, honest no-attribution verdicts), but
observations come from raster_mark.observe: the meta-guided strip
displacement decode. The observation is geometry-guided only (runs /
profile / centroids are identical across variants of the same source), so
one observation per candidate page scores against every marked variant.
Word-shift does not exist in this carrier; word cells report as absent.
"""
import json
import os

from . import store
from . import raster_mark
from .render_pdf import load_doc_meta
from .scan import (binom_p, margin_check, MARGIN_RULE_TEXT, P_THRESHOLD,
                   MIN_BITS)


def _page_meta(meta, page_index):
    return next(p for p in meta["pages"] if p["page_index"] == page_index)


def attribute(manifest, img_path, workdir, source):
    test_id = manifest["test_id"]
    marked = [d for d in manifest["docs"] if d["marked"]]
    metas = {d["doc_id"]: load_doc_meta(test_id, d["doc_id"]) for d in marked}
    layout = metas[marked[0]["doc_id"]]
    result = {"test_id": test_id, "source": source,
              "timestamp": store.now_utc(),
              "attribution_rule": {"p_threshold": P_THRESHOLD,
                                   "min_bits": MIN_BITS,
                                   "correction": "bonferroni x n_variants",
                                   "margin": MARGIN_RULE_TEXT}}

    # Try each marked page: direct decode first, page-crop retry second.
    candidates, last = [], {}
    for pg in layout["pages"]:
        if not pg["slots"]:
            continue
        obs = raster_mark.observe(img_path, pg, workdir=workdir)
        path = "raster"
        if not obs.get("ok"):
            obs = raster_mark.observe(img_path, pg, crop=True,
                                      workdir=workdir)
            path = "raster-crop"
        last = obs
        if obs.get("ok"):
            candidates.append((pg["page_index"], obs, path))

    if not candidates:
        counts = {pg["page_index"]: len(pg["runs"])
                  for pg in layout["pages"] if pg["slots"]}
        result.update({
            "path_used": "raster",
            "deskew_deg": last.get("deskew_deg"),
            "verdict": {"attributed": False, "reason": "segmentation"},
            "note": ("The capture could not be aligned to any marked page "
                     f"of this document (pages carry {counts} text strips). "
                     "Check that the photo shows one full page, roughly "
                     "upright, with the whole page in frame.")})
        return result

    best = None
    for page_index, obs, path in candidates:
        rows = []
        for d in marked:
            ok, tot = raster_mark.score(obs,
                                        _page_meta(metas[d["doc_id"]],
                                                   page_index))
            rows.append({"doc_id": d["doc_id"], "label": d["label"],
                         "line_ok": ok, "line_tot": tot,
                         "line_acc": round(ok / tot, 3) if tot else None,
                         "word_ok": None, "word_tot": None, "word_acc": None,
                         "ok": ok, "tot": tot,
                         "acc": round(ok / tot, 3) if tot else None,
                         "p_value": binom_p(ok, tot)})
        rows.sort(key=lambda r: (r["acc"] or 0), reverse=True)
        # Pick the candidate page by strength of evidence (top row's exact
        # binomial p), not by accuracy: a degenerate 1-strip fit against
        # the wrong page's meta reads 1/1 = 100% and would beat the true
        # page's 9/10 on accuracy alone.
        if best is None or (rows[0]["p_value"] or 1.0) < \
                (best[1][0]["p_value"] or 1.0):
            best = (page_index, rows, obs, path)

    page_index, rows, obs, path = best
    n_var = len(marked)
    for r in rows:
        r["p_adj"] = min(1.0, r["p_value"] * n_var) \
            if r["p_value"] is not None else None
    top, second = rows[0], (rows[1] if len(rows) > 1 else None)
    evid_ok = (top["p_adj"] is not None and top["p_adj"] <= P_THRESHOLD
               and top["tot"] >= MIN_BITS)
    sep_ok, gap_bits, need_bits = margin_check(top, second)
    attributed = evid_ok and sep_ok
    result.update({
        "path_used": path, "deskew_deg": obs.get("deskew_deg"),
        "quality": obs.get("quality"),
        "page_index": page_index, "scores": rows,
        "verdict": {
            "attributed": attributed,
            "doc_id": top["doc_id"] if attributed else None,
            "label": top["label"] if attributed else None,
            "acc": top["acc"], "tot": top["tot"],
            "p_value": top["p_value"], "p_adj": top["p_adj"],
            "margin": round((top["acc"] or 0) - (second["acc"] or 0), 3)
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
        elif top["tot"] < MIN_BITS:
            result["note"] = (f"Only {top['tot']} line strips were readable "
                              f"on this page (the rule needs {MIN_BITS}). "
                              "Pages with more regular text lines carry "
                              "more evidence.")
        else:
            result["note"] = ("No variant separates from chance at the "
                              "stated threshold. Expected for a control "
                              "print, a foreign document, or a capture too "
                              "degraded to read.")
    return result


def run_scan(manifest, img_path, source, scan_pair=None):
    scan_id, sdir = scan_pair or store.new_scan_dir(manifest["test_id"])
    result = attribute(manifest, img_path, sdir, source)
    result["scan_id"] = scan_id
    with open(os.path.join(sdir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    return result
