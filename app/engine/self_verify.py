"""Generate-time self-verification guard.

After a campaign's variants are generated, decode each variant's OWN clean
render through the *real* investigation decoder and refuse to publish the
campaign unless a perfect capture of copy N would attribute to copy N. This
catches documents whose invisible marks do not round-trip at all (heading-heavy
or graphic PDFs, sparse text) BEFORE anyone prints and distributes them.

Contract:
  * Uses the same decode path an investigation uses: ``runner_for(manifest)`` ->
    ``.attribute()`` -> ``scan.pooled_verdict``. No shortcut check.
  * Fail closed: a variant that does not self-attribute, OR any exception,
    rejects the whole campaign. There is no proceed-anyway override.
  * Threshold (evidence-set, see docs): each checked variant must self-attribute
    to itself AND its clean pooled self-accuracy must be >= MIN_SELF_ACC. On the
    known-good documents the true variant self-attributes at accuracy 1.00
    (p_adj <= 1e-4); the brochure/sparse failures do not self-attribute at all.
    MIN_SELF_ACC sits in the empty gap between (0.70 fail) and (1.00 pass).
  * Round-trip readability is a property of the document layout (all variants
    share the same slots), so checking a small sample of variants is enough to
    detect a non-decodable document; MAX_VARIANTS_CHECKED bounds the cost so a
    300-copy campaign does not re-decode 300 variants.
"""
import os
import re
import glob
import tempfile

from . import scan, store

MIN_SELF_ACC = 0.95        # a clean render has no channel loss; near-perfect
MAX_VARIANTS_CHECKED = 3   # round-trip is a document/layout property
MAX_PAGES_CHECKED = 8      # bound cost on very long documents

# Two distinct failure causes with DIFFERENT remedies, so the message must say
# which one applies:
#  * unreadable -- the marks were embedded but do not read back on THIS document
#    type (the true copy reads at chance / a decoy wins). The layout defeats the
#    decoder: heavy headings, graphics, columns, unusual leading. Fix = switch
#    the document (paste the text, or use a dense body-text PDF).
#  * too little content -- the marks read back correctly but there are too few
#    to clear the attribution rule even from a flawless capture. Fix = give it
#    more markable text (a longer document, or more pages).
REJECT_REASON_UNREADABLE = (
    "This document's invisible marks do not read back on this kind of document, "
    "so a leaked photo could not be attributed to a source, and the campaign "
    "was not created. Heavy headings, graphics, columns, or unusual line "
    "spacing can stop the marks being read. Fix: switch to the rendered carrier "
    "(paste the text, or let the app extract it, so the page is re-typeset), or "
    "use a document that is mostly continuous body text."
)
REJECT_REASON_CAPACITY = (
    "This document carries too few readable marks to identify a copy -- even "
    "from a perfect scan the marks are correct but there are not enough of them "
    "to trace a leak, so the campaign was not created. Fix: use a longer "
    "document, or include more pages of regular body text, so there is more "
    "room to carry the invisible marks."
)
# Kept for callers/tests referring to the old name; defaults to the readability
# message.
REJECT_REASON = REJECT_REASON_UNREADABLE

# A failed variant that still read its own marks at >= this accuracy is a
# capacity problem (too few marks), not a readability problem (marks misread).
_READABLE_ACC = 0.90


def runner_for(manifest):
    """The attribution module for a carrier -- the SAME dispatch the scan
    routes use. Imported lazily to avoid a heavy import at module load."""
    from . import scan_pdf, scan_raster
    return {"pdf_preserved": scan_pdf,
            "pdf_raster": scan_raster,
            "pdf_vector": scan_raster}.get(manifest.get("type"), scan)


_SOURCE = {"kind": "self_verify", "synthetic": True, "framing": "full",
           "label": "clean self-render"}


def _variant_renders(manifest, doc_id):
    """(page_index, image_path) for a variant's clean page renders: the marked
    page PNGs the generator already produced, or a 300-dpi rasterization of the
    variant's marked PDF. Higher-capacity pages are not known here, so pages
    are returned in order; the caller stops once a variant self-attributes."""
    ddir = os.path.join(store.test_dir(manifest["test_id"]), "docs", doc_id)
    pngs = sorted(p for p in glob.glob(os.path.join(ddir, "page*.png"))
                  if "thumb" not in os.path.basename(p))
    out = []
    for p in pngs:
        m = re.search(r"page(\d+)", os.path.basename(p))
        if m:
            out.append((int(m.group(1)), p))
    if out:
        return out
    pdf = os.path.join(ddir, "document.pdf")
    if os.path.exists(pdf):
        import fitz
        d = fitz.open(pdf)
        for i in range(len(d)):
            pix = d[i].get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
            p = os.path.join(tempfile.mkdtemp(), f"page{i}.png")
            pix.save(p)
            out.append((i, p))
    return out


def _self_attributes(pooled, doc_id):
    return bool(pooled
                and pooled.get("attributed")
                and pooled.get("attributed_doc") == doc_id
                and (pooled.get("agreement") or 0) >= MIN_SELF_ACC)


def _check_variant(manifest, runner, doc_id):
    """Decode a variant's own clean renders, one page at a time (passing the
    page index so the real decoder does not robust-search the other pages), and
    pool them exactly as an investigation would. Stops as soon as the variant
    conclusively self-attributes. Returns (self_ok, summary)."""
    results = []
    for page_index, img in _variant_renders(manifest, doc_id)[:MAX_PAGES_CHECKED]:
        wd = tempfile.mkdtemp()
        r = runner.attribute(manifest, img, wd, _SOURCE, only_pages=[page_index])
        if r.get("scores"):
            results.append(r)
        if _self_attributes(scan.pooled_verdict(results), doc_id):
            break
    pooled = scan.pooled_verdict(results) or {}
    self_ok = _self_attributes(pooled, doc_id)
    return self_ok, {"doc_id": doc_id,
                     "attributed": pooled.get("attributed"),
                     "attributed_doc": pooled.get("attributed_doc"),
                     "agreement": pooled.get("agreement"),
                     "n_bits": pooled.get("n_bits"),
                     "p_adj": pooled.get("p_adj"),
                     "self_ok": self_ok}


def verify(manifest):
    """Self-verify a freshly generated campaign. Returns
    ``{"ok": bool, "reason": str|None, "detail": {...}}``. Fail closed: any
    exception is reported as a rejection, never as a pass."""
    try:
        runner = runner_for(manifest)
        marked = [d for d in manifest.get("docs", []) if d.get("marked")]
        checked = marked[:MAX_VARIANTS_CHECKED]
        summaries, failed = [], []
        for d in checked:
            ok, summary = _check_variant(manifest, runner, d["doc_id"])
            summaries.append(summary)
            if not ok:
                failed.append(d["doc_id"])
        detail = {"checked": summaries, "min_self_acc": MIN_SELF_ACC,
                  "n_variants_checked": len(checked)}
        if failed:
            # Distinguish the two causes: if every failed variant still read its
            # OWN marks accurately (>= _READABLE_ACC), the marks are fine but too
            # few (capacity). If any failed variant read its marks poorly (a
            # decoy won / chance), the document type defeats the decoder.
            fsum = [s for s in summaries if not s["self_ok"]]
            unreadable = any(s["agreement"] is not None
                             and s["agreement"] < _READABLE_ACC for s in fsum)
            cause = "unreadable" if unreadable else "too_little_content"
            reason = (REJECT_REASON_UNREADABLE if unreadable
                      else REJECT_REASON_CAPACITY)
            detail["failed_variants"] = failed
            detail["cause"] = cause
            return {"ok": False, "reason": reason, "detail": detail}
        return {"ok": True, "reason": None, "detail": detail}
    except Exception as e:  # fail closed
        return {"ok": False, "reason": REJECT_REASON_UNREADABLE,
                "detail": {"error": f"{type(e).__name__}: {e}"}}
