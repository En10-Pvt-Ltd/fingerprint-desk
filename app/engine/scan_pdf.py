# SPDX-License-Identifier: Apache-2.0
"""Attribution for formatting-preserved PDF tests (Stage 2 M4).

Same product semantics as engine/scan.py (Bonferroni-corrected exact
binomial threshold, honest no-attribution verdicts, control framing), but
observations come from engine/pdf_scan.py: line-shift triplets located via
the meta's band layout. Word-shift does not exist in this carrier, so word
cells are reported as absent (None), never as 'erased'.
"""
import json
import os

from . import store
from . import pdf_scan
from .render_pdf import load_doc_meta
from .scan import (binom_p, margin_check, MARGIN_RULE_TEXT, P_THRESHOLD,
                   MIN_BITS)


def attribute(manifest, img_path, workdir, source, only_pages=None):
    # only_pages: restrict the page-layout search to these page indices. The
    # self-verify guard passes the page it is decoding so a clean render is not
    # robust-searched against every other page (identical observe/score, just
    # not wasted on pages this image is not). None = search all (normal scans).
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

    # Try every page layout: clean observation first, then the robust
    # real-photo path. First page whose line count matches wins a candidacy.
    attempts = []
    candidates = []
    for pg in layout["pages"]:
        if not pg["bands"]:
            continue
        if only_pages is not None and pg["page_index"] not in only_pages:
            continue
        obs = pdf_scan.observe_page(img_path, pg)
        if not obs.get("ok"):
            robust = pdf_scan.observe_page_robust(
                img_path, pg, os.path.join(workdir, f"p{pg['page_index']}"))
            attempts.append((pg, obs, robust))
            obs = robust
        else:
            attempts.append((pg, obs, None))
        if obs.get("ok"):
            candidates.append((pg["page_index"], obs))

    if not candidates:
        counts = {pg["page_index"]: pg["n_lines_total"]
                  for pg in layout["pages"] if pg["bands"]}
        last = attempts[-1][2] or attempts[-1][1] if attempts else {}
        result.update({
            "path_used": "robust", "deskew_deg": last.get("deskew_deg"),
            "n_lines_found": last.get("n_lines_found"),
            "verdict": {"attributed": False, "reason": "segmentation"},
            "note": ("No page of this document matched the capture's line "
                     f"structure (pages have {counts} text lines). Check "
                     "that the photo shows one full page, roughly upright, "
                     "with the whole text block in frame.")})
        return result

    best = None
    for page_index, obs in candidates:
        rows = []
        for d in marked:
            ok, tot = pdf_scan.score_page(obs["bands"],
                                          metas[d["doc_id"]]["pages"][page_index])
            rows.append({"doc_id": d["doc_id"], "label": d["label"],
                         "line_ok": ok, "line_tot": tot,
                         "line_acc": round(ok / tot, 3) if tot else None,
                         "word_ok": None, "word_tot": None, "word_acc": None,
                         "ok": ok, "tot": tot,
                         "acc": round(ok / tot, 3) if tot else None,
                         "p_value": binom_p(ok, tot)})
        rows.sort(key=lambda r: (r["acc"] or 0), reverse=True)
        if best is None or (rows[0]["acc"] or 0) > (best[1][0]["acc"] or 0):
            best = (page_index, rows, obs)

    page_index, rows, obs = best
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
        "path_used": obs.get("path"), "deskew_deg": obs.get("deskew_deg"),
        "n_lines_found": obs.get("n_lines_found"),
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
            result["note"] = (f"Only {top['tot']} line bits were observable "
                              f"on this page (the rule needs {MIN_BITS}). "
                              "Pages with more regular body text carry more "
                              "evidence.")
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
