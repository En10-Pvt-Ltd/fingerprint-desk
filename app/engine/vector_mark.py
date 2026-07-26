# SPDX-License-Identifier: Apache-2.0
"""Vector line-shift embedding for text-as-outlines PDFs.

Secure exam-paper PDFs are often exported with every glyph converted to
filled vector paths (no text objects), which defeats Stage 2's
content-stream text-op marking, while the pages are born-digital vectors
— too clean and too structured for the raster pathway's assumptions.
This module marks such PDFs by translating every path of a chosen text
line vertically by +/-SHIFT_PT in the content stream (coordinate edit of
the path construction operands), in the public triplet convention
(control, marked, control; bit 1 = middle line down on paper). Vector
quality is preserved exactly; controls are byte copies.

The reference frame is a 300-dpi render of the unmarked page. The meta
uses the SAME schema as raster_mark (runs / native profile / centroids /
slots at 300-dpi rows, shift = 2 px = 0.48 pt), so decoding reuses
raster_mark.observe / score verbatim — meta-guided sub-pixel profile
correlation with the never-shifted runs as zero reference.

Markability guard: a line can only be shifted if every painted path that
overlaps its row band lies FULLY inside it (a vertical table rule or
border crossing the band would otherwise be cut), and no image placement
overlaps the band. Pages whose painted content sits under a rotated or
sheared CTM are not marked at all.
"""
import io

import cv2
import fitz
import numpy as np
import pikepdf

from . import REPO  # noqa: F401
import encode
from . import raster_mark

DPI = 300
PAYLOAD_BITS = 64
SHIFT_PX = 2                     # at DPI, = 0.48 pt (validated amplitude)
SHIFT_PT = SHIFT_PX * 72.0 / DPI
MIN_RUN_H, MAX_RUN_H = 8, 110    # px at DPI
MIN_GAP = 12                     # px at DPI
INK_ROW_FRAC = 0.03
BAND_MARGIN_PT = 0.6             # slack when testing full containment

PATH_OPS = {"m", "l", "c", "v", "y", "re"}
PAINT_OPS = {"f", "F", "f*", "B", "B*", "b", "b*", "S", "s"}
# indices of the y operands for each construction op
_Y_IDX = {"m": [1], "l": [1], "c": [1, 3, 5], "v": [1, 3], "y": [1, 3],
          "re": [1]}


# ---- render-side analysis (raster conventions at 300 dpi) ----------------------
def _render_gray(doc, pno):
    pix = doc[pno].get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height,
                                                        pix.width).copy()


def _segment(gray):
    on = (gray < 128).sum(axis=1) > INK_ROW_FRAC * gray.shape[1]
    runs, r0 = [], None
    for k, v in enumerate(on):
        if v and r0 is None:
            r0 = k
        elif not v and r0 is not None:
            runs.append((r0, k))
            r0 = None
    if r0 is not None:
        runs.append((r0, len(on)))
    return [r for r in runs if r[1] - r[0] >= MIN_RUN_H]


# ---- content-stream walk -------------------------------------------------------
def _mat_mul(m1, m0):
    """Compose: apply m1 (the new cm) then m0 (current CTM)."""
    a1, b1, c1, d1, e1, f1 = m1
    a0, b0, c0, d0, e0, f0 = m0
    return (a1 * a0 + b1 * c0, a1 * b0 + b1 * d0,
            c1 * a0 + d1 * c0, c1 * b0 + d1 * d0,
            e1 * a0 + f1 * c0 + e0, e1 * b0 + f1 * d0 + f0)


def _walk_paths(ops):
    """Segment the operator list into painted path records.

    Returns (paths, images, rotated) where each path is
    {y0, y1 (device pt, ascending), ops: [op indices], d: CTM y-scale at
    paint time}; images are (y0, y1) device intervals of Do placements;
    rotated is True if any painted path or image sits under a CTM with
    shear/rotation (b or c nonzero).
    """
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack = []
    cur = []                    # op indices of current path construction
    ys = []                     # device-space y of current path's points
    rotated = False
    paths, images = [], []
    for i, inst in enumerate(ops):
        op = str(inst.operator)
        if op == "q":
            stack.append(ctm)
        elif op == "Q":
            ctm = stack.pop() if stack else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        elif op == "cm":
            m = tuple(float(x) for x in inst.operands)
            ctm = _mat_mul(m, ctm)
        elif op in PATH_OPS:
            cur.append(i)
            a, b, c, d, e, f = ctm
            nums = [float(x) for x in inst.operands]
            if op == "re":
                x0, y0, w, h = nums
                pts = [(x0, y0), (x0 + w, y0 + h)]
            else:
                pts = [(nums[j], nums[j + 1]) for j in range(0, len(nums), 2)]
            for x, y in pts:
                ys.append(b * x + d * y + f)
            if b != 0.0 or c != 0.0:
                rotated = True
        elif op in PAINT_OPS:
            if cur and ys:
                paths.append({"y0": min(ys), "y1": max(ys),
                              "ops": list(cur), "d": ctm[3]})
            cur, ys = [], []
        elif op == "n":
            cur, ys = [], []              # clip consumption, not painted
        elif op == "Do":
            a, b, c, d, e, f = ctm
            if b != 0.0 or c != 0.0:
                rotated = True
            corner_ys = [b * x + d * y + f for x in (0.0, 1.0)
                         for y in (0.0, 1.0)]
            images.append((min(corner_ys), max(corner_ys)))
    return paths, images, rotated


def _ext_band_pt(runs, j, page_h_pt):
    """Device-pt interval a line OWNS: its render band expanded half-way
    into the neighboring gaps (capped). The binarized render underestimates
    glyph extents — descenders and ascenders poke a couple of points past
    the ink band — so containment must be judged against mid-gap
    boundaries, exactly the decoder's window notion. A table rule or
    border still fails: it crosses the half-gap line."""
    a, b = runs[j]
    gap_up = (a - runs[j - 1][1]) if j > 0 else MIN_GAP
    gap_dn = (runs[j + 1][0] - b) if j + 1 < len(runs) else MIN_GAP
    ext_up = min(6.0, 0.5 * gap_up * 72.0 / DPI)
    ext_dn = min(6.0, 0.5 * gap_dn * 72.0 / DPI)
    y_top = page_h_pt - a * 72.0 / DPI + ext_up
    y_bot = page_h_pt - b * 72.0 / DPI - ext_dn
    return (y_bot, y_top)


def _classify(band, paths, images):
    """(inside_paths, ok): paths fully inside the band vs any partial
    overlap / image overlap making the band unmarkable."""
    lo, hi = band
    lo -= BAND_MARGIN_PT
    hi += BAND_MARGIN_PT
    inside = []
    for p in paths:
        if p["y1"] < lo or p["y0"] > hi:
            continue
        if p["y0"] >= lo and p["y1"] <= hi:
            inside.append(p)
        else:
            return [], False
    for y0, y1 in images:
        if not (y1 < lo or y0 > hi):
            return [], False
    return inside, bool(inside)


# ---- analysis ------------------------------------------------------------------
def analyze(src_bytes, pages):
    """Per page: 300-dpi runs/profile/centroids plus VALID triplets (middle
    band shiftable per the containment guard)."""
    doc = fitz.open(stream=src_bytes, filetype="pdf")
    pdf = pikepdf.open(io.BytesIO(src_bytes))
    out = []
    for pno in pages:
        if pno >= doc.page_count:
            break
        gray = _render_gray(doc, pno)
        page_h_pt = doc[pno].rect.height
        runs = _segment(gray)
        prof = ((gray < 128).sum(axis=1)).astype(np.float64)
        cents = []
        for a, b in runs:
            w = prof[a:b]
            cents.append(round(float((np.arange(a, b) * w).sum() / w.sum()),
                               3) if w.sum() > 0 else (a + b) / 2.0)
        ops = list(pikepdf.parse_content_stream(pdf.pages[pno]))
        paths, images, rotated = _walk_paths(ops)
        trips = []
        if not rotated:
            i = 0
            while i + 2 < len(runs):
                trip = runs[i:i + 3]
                a, b = trip[1]
                ok = all(MIN_RUN_H <= rb - ra <= MAX_RUN_H
                         for ra, rb in trip)
                ok = ok and (a - trip[0][1]) >= MIN_GAP \
                        and (trip[2][0] - b) >= MIN_GAP
                if ok:
                    inside, mk = _classify(
                        _ext_band_pt(runs, i + 1, page_h_pt), paths, images)
                    ok = mk
                if ok:
                    trips.append((i, i + 1, i + 2))
                    i += 3
                else:
                    i += 1
        out.append({"page_index": pno, "img_w": gray.shape[1],
                    "img_h": gray.shape[0], "page_h_pt": page_h_pt,
                    "deskew_deg": 0.0,
                    "runs": [[int(a), int(b)] for a, b in runs],
                    "profile": [int(x) for x in prof],
                    "centroids": cents, "triplets": trips,
                    "rotated": rotated})
    pdf.close()
    doc.close()
    return out


# ---- embedding -----------------------------------------------------------------
def _shift_ops(ops, path_recs, delta_pt):
    """Add delta_pt (device points, +up in PDF space) to the y operands of
    every construction op of the given path records, each through its own
    CTM y-scale."""
    for rec in path_recs:
        du = delta_pt / rec["d"]
        for oi in rec["ops"]:
            inst = ops[oi]
            op = str(inst.operator)
            nums = [float(x) for x in inst.operands]
            for yi in _Y_IDX[op]:
                nums[yi] = round(nums[yi] + du, 4)
            ops[oi] = pikepdf.ContentStreamInstruction(
                nums, pikepdf.Operator(op))


def embed(src_bytes, seed, pages=range(5), unmarked=False):
    """Return (pdf_bytes, meta). Marked lines' paths are translated by
    +/-SHIFT_PT; everything else in the stream is untouched. Controls are
    byte copies of the source."""
    pages = [p for p in pages]
    ana = analyze(src_bytes, pages)
    payload = encode.prn_bits(seed, PAYLOAD_BITS)
    meta = {"version": 3, "kind": "vector_lineshift", "seed": seed,
            "unmarked": bool(unmarked), "payload": payload,
            "shift_px": SHIFT_PX, "dpi": DPI,
            "n_pages_marked": len(ana), "pages": []}
    slot = 0
    pdf = pikepdf.open(io.BytesIO(src_bytes))
    for pg in ana:
        mpage = {"page_index": pg["page_index"], "img_w": pg["img_w"],
                 "img_h": pg["img_h"], "runs": pg["runs"],
                 "deskew_deg": 0.0, "profile": pg["profile"],
                 "centroids": pg["centroids"], "slots": []}
        page = pdf.pages[pg["page_index"]]
        ops = list(pikepdf.parse_content_stream(page))
        paths, images, rotated = _walk_paths(ops)
        touched = False
        for (i, j, k) in pg["triplets"]:
            bit = payload[slot % PAYLOAD_BITS]
            slot += 1
            a, b = pg["runs"][j]
            rec = {"runs_idx": [i, j, k], "mid": [a, b], "bit": bit,
                   "delta_px": 0}
            if not unmarked and not rotated:
                runs_t = [tuple(r) for r in pg["runs"]]
                inside, mk = _classify(
                    _ext_band_pt(runs_t, j, pg["page_h_pt"]), paths, images)
                if mk:
                    rec["delta_px"] = SHIFT_PX if bit == 1 else -SHIFT_PX
                    # bit 1 = down on paper = smaller PDF y (y-up space)
                    _shift_ops(ops, inside,
                               -SHIFT_PT if bit == 1 else SHIFT_PT)
                    touched = True
            mpage["slots"].append(rec)
        if touched:
            page.Contents = pdf.make_stream(
                pikepdf.unparse_content_stream(ops))
        meta["pages"].append(mpage)
    meta["n_slots"] = slot
    if unmarked or slot == 0:
        pdf.close()
        return src_bytes, meta
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue(), meta


# ---- decoding (delegates to the raster meta-guided decoder) --------------------
observe = raster_mark.observe
score = raster_mark.score
