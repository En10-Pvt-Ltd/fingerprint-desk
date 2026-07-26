# SPDX-License-Identifier: Apache-2.0
"""Raster line-shift embedding for image-only (scanned/photographed) PDFs.

Stage 2 (pdf_mark) moves text-showing operations in a PDF content stream,
so it needs text objects. Scanned papers have none: each page is one
full-page image. This module embeds the same public line-shift convention
directly in the page image: whole text-line pixel-row bands are nudged
+/-SHIFT_PX at the image's native scale, in triplets (control, marked,
control), bit 1 = middle line down. Everything outside the shifted bands
is pixel-identical (images are re-embedded losslessly as PNG), so tables,
figures, stamps and the two-column layout are preserved exactly.

Two-column note: encode and decode both use the full-width row profile,
so a "line" is a horizontal strip across both columns and a shift moves
the strip as one unit. The convention is consistent on both sides; column
misalignment only costs capacity (fewer clean strips), never correctness.

Decode (meta-guided, hardened on this pathway's synthetic matrix):
binarize (flat-field + Otsu), rotate the capture back into the NATIVE
frame (capture skew minus the meta's recorded native skew), fit the
meta's run pattern with a tight-band comb search plus mutual-nearest
IRLS refinement, resample the capture's ink profile into native rows
(box prefilter), then measure each strip's sub-pixel displacement by
local normalized cross-correlation against the meta's stored native
profile. Runs that are never shifted (everything but slot middles)
calibrate the local zero reference; the bit is the deviation's sign,
with an erasure band so borderline slots abstain instead of guessing.
"""
import io

import cv2
import fitz
import numpy as np

from . import REPO  # noqa: F401
import decode as dec
import encode

PAYLOAD_BITS = 64
SHIFT_PX = 2                  # at the page image's native scale
MIN_RUN_H, MAX_RUN_H = 5, 40  # plausible text-line strip heights
MIN_GAP = 6                   # clear rows required above AND below a marked run
INK_ROW_FRAC = 0.03           # row is "on" if ink pixels exceed this width share
                              # (absolute counts admit faint rules/box borders as
                              # "lines"; marks must ride real text rows)


# ---- image access ---------------------------------------------------------------
# A page only counts as a scan if its single drawn image actually covers
# the sheet; a decorative logo/banner/watermark on an otherwise vector
# page must not capture this carrier.
MIN_COVER_AREA = 0.7          # image bbox area / page area
MIN_COVER_SIDE = 0.6          # image bbox width & height / page width & height


def _page_image(doc, pno):
    """(rgb array, xref) of the page's single RENDERED full-page image.
    get_images() also lists stale resource entries (e.g. the original left
    behind by replace_image), so prefer the actually-drawn image."""
    info = [i for i in doc[pno].get_image_info(xrefs=True) if i.get("xref")]
    drawn = [i["xref"] for i in info]
    prect = doc[pno].rect
    page_area = prect.width * prect.height
    for i in info:
        bbox = fitz.Rect(i["bbox"])
        if page_area <= 0 \
                or bbox.width * bbox.height < MIN_COVER_AREA * page_area \
                or bbox.width < MIN_COVER_SIDE * prect.width \
                or bbox.height < MIN_COVER_SIDE * prect.height:
            raise ValueError(f"page {pno}: image does not cover the page "
                             "(not a scan)")
    if len(set(drawn)) == 1:
        xref = drawn[0]
    else:
        imgs = doc[pno].get_images(full=True)
        if len(imgs) != 1:
            raise ValueError(f"page {pno}: expected 1 page image, "
                             f"found {len(imgs)} (drawn: {drawn})")
        xref = imgs[0][0]
    pix = fitz.Pixmap(doc, xref)
    if pix.colorspace and pix.colorspace.n != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width,
                                                       pix.n)[:, :, :3].copy()
    return arr, xref


def _normalize(gray):
    """Flat-field normalization (same recipe as the robust capture path):
    divide by a morphological-close background estimate so shading in a
    photographed page cannot swallow the row profile."""
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kern)
    return np.clip(gray.astype(np.float64) / np.maximum(bg, 1) * 255,
                   0, 255).astype(np.uint8)


def _segment(norm):
    """Full-width ink-row runs [(a, b), ...] on a normalized gray image."""
    _, binv = cv2.threshold(norm, 0, 255,
                            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    on = (binv > 0).sum(axis=1) > INK_ROW_FRAC * norm.shape[1]
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


def _triplets(runs, img_h):
    """Non-overlapping consecutive run triples whose middle run can shift
    +/-SHIFT_PX without touching a neighbor."""
    out, i = [], 0
    while i + 2 < len(runs):
        trip = runs[i:i + 3]
        ok = all(MIN_RUN_H <= b - a <= MAX_RUN_H for a, b in trip)
        a, b = trip[1]
        gap_up = a - trip[0][1]
        gap_dn = trip[2][0] - b
        ok = ok and gap_up >= MIN_GAP and gap_dn >= MIN_GAP
        ok = ok and a - (SHIFT_PX + 1) >= 0 and b + SHIFT_PX + 1 <= img_h
        if ok:
            out.append((i, i + 1, i + 2))
            i += 3
        else:
            i += 1
    return out


# ---- analysis / embedding -------------------------------------------------------
def analyze(src_bytes, pages):
    """Per requested page: image size, runs, markable triplets."""
    doc = fitz.open(stream=src_bytes, filetype="pdf")
    out = []
    for pno in pages:
        if pno >= doc.page_count:
            break
        rgb, xref = _page_image(doc, pno)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        norm = _normalize(gray)
        runs = _segment(norm)
        trips = _triplets(runs, gray.shape[0])
        # Native (unmarked) ink centroid of every run: the decode-side
        # reference for the triplet-local interpolation statistic.
        _, binv = cv2.threshold(norm, 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        prof = (binv > 0).sum(axis=1).astype(np.float64)
        cents = []
        for a, b in runs:
            w = prof[a:b]
            cents.append(round(float((np.arange(a, b) * w).sum() / w.sum()),
                               3) if w.sum() > 0 else (a + b) / 2.0)
        # The runs/centroids live in the NATIVE frame (shifts are applied
        # to native rows; the source's own skew stays untouched). Record
        # the native frame's deskew angle so the decoder can rotate a
        # capture back INTO this frame instead of to level — a level frame
        # would merge/split different rows than the meta describes. The
        # full native ink profile is the decode-side correlation template.
        _, native_deg = dec.deskew(255 - binv)
        out.append({"page_index": pno, "img_w": gray.shape[1],
                    "img_h": gray.shape[0], "xref": xref,
                    "deskew_deg": round(float(native_deg), 3),
                    "runs": [[int(a), int(b)] for a, b in runs],
                    "profile": [int(x) for x in prof],
                    "centroids": cents, "triplets": trips})
    doc.close()
    return out


def _shift_band(img, a, b, delta):
    """Move rows [a-1, b+1) of img by delta pixels (positive = down),
    filling vacated rows from the adjacent background row. Caller
    guarantees clearance."""
    n = abs(int(delta))
    band = img[a - 1:b + 1].copy()
    if delta > 0:
        img[a - 1 + n:b + 1 + n] = band
        img[a - 1:a - 1 + n] = img[a - 2]
    else:
        img[a - 1 - n:b + 1 - n] = band
        img[b + 1 - n:b + 1] = img[b + 1]


def embed(src_bytes, seed, pages=range(5), unmarked=False):
    """Return (pdf_bytes, meta). Marked pages get their image replaced by a
    losslessly re-encoded (PNG) copy with line bands shifted; every other
    page object is untouched. Controls are byte copies of the source."""
    pages = [p for p in pages]
    ana = analyze(src_bytes, pages)
    payload = encode.prn_bits(seed, PAYLOAD_BITS)
    meta = {"version": 3, "kind": "raster_lineshift", "seed": seed,
            "unmarked": bool(unmarked), "payload": payload,
            "shift_px": SHIFT_PX, "n_pages_marked": len(ana), "pages": []}
    slot = 0
    doc = fitz.open(stream=src_bytes, filetype="pdf")
    for pg in ana:
        rgb, xref = _page_image(doc, pg["page_index"])
        mpage = {"page_index": pg["page_index"], "img_w": pg["img_w"],
                 "img_h": pg["img_h"], "runs": pg["runs"],
                 "deskew_deg": pg["deskew_deg"], "profile": pg["profile"],
                 "centroids": pg["centroids"], "slots": []}
        touched = False
        for (i, j, k) in pg["triplets"]:
            bit = payload[slot % PAYLOAD_BITS]
            slot += 1
            a, b = pg["runs"][j]
            rec = {"runs_idx": [i, j, k], "mid": [a, b], "bit": bit,
                   "delta_px": 0}
            if not unmarked:
                rec["delta_px"] = SHIFT_PX if bit == 1 else -SHIFT_PX
                _shift_band(rgb, a, b, rec["delta_px"])
                touched = True
            mpage["slots"].append(rec)
        meta["pages"].append(mpage)
        if touched:
            okenc, png = cv2.imencode(".png",
                                      cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            if not okenc:
                raise RuntimeError("PNG encode failed")
            doc[pg["page_index"]].replace_image(xref, stream=png.tobytes())
    meta["n_slots"] = slot
    if unmarked or slot == 0:
        doc.close()
        return src_bytes, meta
    # replace_image rewrites the drawn image object in place (the original
    # image data is gone from the emitted file) but also registers the new
    # image under a second resource name, duplicating the stream;
    # garbage=4 deduplicates identical objects on save.
    out = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return out, meta


# ---- decoding -------------------------------------------------------------------
def observe(img_path, page_meta, crop=False, workdir=None):
    """Decode one captured image of a marked page against its page meta.
    Returns {"ok", "reason"?, "quality", "bits": {slot_index: 0/1/None}}.
    The crop retry writes its intermediate JPEG into workdir when given
    (never next to a committed artifact, where concurrent scans of the
    same source image would race on the path)."""
    gray = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return {"ok": False, "reason": "unreadable image"}
    if crop:
        from run_robust import crop_to_page
        import os
        base = os.path.splitext(os.path.basename(img_path))[0] + "_crop.jpg"
        dst = os.path.join(workdir, base) if workdir \
            else os.path.splitext(img_path)[0] + "_crop.jpg"
        gray = cv2.imread(crop_to_page(img_path, dst, verbose=False),
                          cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return {"ok": False, "reason": "page crop produced an "
                                           "unreadable image"}
    # Binarize FIRST (flat-field + Otsu), then deskew on the binary ink
    # map: raw-gray deskew is hijacked by large dark regions (banners,
    # photos) that dominate the row-variance objective, and scanned
    # sources carry real skew of their own.
    norm = _normalize(gray)
    _, binv0 = cv2.threshold(norm, 0, 255,
                             cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Rotate into the NATIVE frame, not to level: the meta's run pattern
    # was segmented in the source's own (possibly skewed) frame, so only
    # the CAPTURE-added rotation must be removed. deskew() measures total
    # skew; subtracting the recorded native angle leaves the frame the
    # meta describes.
    _, total_deg = dec.deskew(255 - binv0)
    ang = float(total_deg) - float(page_meta.get("deskew_deg", 0.0))
    M = cv2.getRotationMatrix2D((binv0.shape[1] / 2, binv0.shape[0] / 2),
                                ang, 1.0)
    g = cv2.warpAffine(255 - binv0, M,
                       (binv0.shape[1], binv0.shape[0]),
                       flags=cv2.INTER_LINEAR, borderValue=255)
    ink = (g < 128)
    H, W = ink.shape
    prof = ink.sum(axis=1).astype(np.float64)

    # Segment the capture with the SAME convention as the encoder,
    # thresholds scaled to the capture resolution.
    s0 = H / float(page_meta["img_h"])
    wscale = W / float(page_meta["img_w"])
    on = prof > INK_ROW_FRAC * W
    cap_runs, r0 = [], None
    for kk, v in enumerate(on):
        if v and r0 is None:
            r0 = kk
        elif not v and r0 is not None:
            cap_runs.append((r0, kk))
            r0 = None
    if r0 is not None:
        cap_runs.append((r0, len(on)))
    cap_runs = [r for r in cap_runs if r[1] - r[0] >= max(2, MIN_RUN_H * s0 * 0.5)]
    if len(cap_runs) < 3:
        return {"ok": False, "reason": f"only {len(cap_runs)} ink runs"}
    cap_cent = []
    for a0, b0 in cap_runs:
        wgt = prof[a0:b0]
        cap_cent.append(float((np.arange(a0, b0) * wgt).sum() / wgt.sum()))

    # Fit the meta's native run-centroid pattern to the capture's run
    # centroids: scale is known within a few percent (full-page capture),
    # so search s in a tight band and offset over the page, maximizing the
    # number of native runs landing within tolerance of a capture run.
    natives = page_meta.get("centroids") or \
        [(a + b) / 2.0 for a, b in page_meta["runs"]]
    nat = np.asarray(natives, dtype=np.float64)
    cc = np.asarray(cap_cent, dtype=np.float64)
    tol = max(3.0, 0.35 * float(np.median(np.diff(nat))) * s0)
    best = (None, -1.0)
    for s in np.linspace(0.94 * s0, 1.06 * s0, 25):
        pred0 = nat * s
        lo = -pred0[0]
        hi = (H - 1) - pred0[-1]
        if hi < lo:
            continue
        for b in np.linspace(lo, hi, 61):
            pred = pred0 + b
            # most runs matched wins; ties broken by total distance
            d = np.abs(pred[:, None] - cc[None, :]).min(axis=1)
            score = (float((d < tol).sum())
                     - 0.001 * float(d.clip(0, 5 * tol).sum()))
            if score > best[1]:
                best = ((s, b), score)
    if best[0] is None:
        return {"ok": False, "reason": "run pattern fit failed"}
    s, b = best[0]

    # Refine (s, b) over MUTUALLY-nearest matches with iterated reweighted
    # least squares (residuals clipped at tol/2). A plain nearest-neighbor
    # LS gets poisoned by wrong matches and can drag the scale several
    # percent off, which displaces every measurement window; reject any
    # refinement that leaves the plausible scale band.
    s_grid, b_grid = s, b
    for _ in range(3):
        pairs = []
        for ni, y in enumerate(nat):
            pred = y * s + b
            jj = int(np.argmin(np.abs(cc - pred)))
            back = int(np.argmin(np.abs(nat * s + b - cc[jj])))
            if back == ni and abs(cc[jj] - pred) < tol:
                pairs.append((y, cc[jj]))
        if len(pairs) < 3:
            break
        A = np.array([[y, 1.0] for y, _ in pairs])
        v = np.array([c for _, c in pairs])
        res = v - A @ np.array([s, b])
        wts = 1.0 / (1.0 + (res / (0.5 * tol)) ** 2)
        Aw = A * wts[:, None]
        try:
            s_new, b_new = np.linalg.lstsq(Aw, v * wts, rcond=None)[0]
        except np.linalg.LinAlgError:
            break
        if not (0.90 * s0 <= s_new <= 1.10 * s0):
            s, b = s_grid, b_grid
            break
        s, b = float(s_new), float(b_new)
    matched = 0
    for ni, y in enumerate(nat):
        if np.abs(cc - (y * s + b)).min() < tol:
            matched += 1
    quality = matched / float(len(nat))

    # Measurement: local PROFILE CORRELATION against the meta's stored
    # native ink profile. The capture profile is resampled into native row
    # coordinates through the fitted transform; each run's displacement is
    # the sub-pixel offset maximizing normalized cross-correlation in a
    # small window around the run. Runs that are never shifted (everything
    # but slot middles — public convention) calibrate the local
    # zero-displacement reference, so residual transform error and
    # perspective drift cancel. Correlation is insensitive to window
    # placement, blur and rebinarization, where windowed centroids are
    # not.
    runs_nat = page_meta["runs"]
    natprof = np.asarray(page_meta["profile"], dtype=np.float64)
    h_nat = len(natprof)
    # Anti-aliased resample of the capture profile into native rows: each
    # native row's value is the MEAN of the capture profile over that
    # row's span (box prefilter via cumulative sum). Point-sampling every
    # s-th row aliases the fine structure whenever the capture is higher
    # resolution than the native image.
    csum = np.concatenate([[0.0], np.cumsum(prof)])
    lo_e = np.clip(np.arange(h_nat) * s + b - 0.5 * s, 0, H - 1e-9)
    hi_e = np.clip(lo_e + s, lo_e + 1e-6, H)

    def _integral(x):
        i = np.floor(x).astype(int)
        frac = x - i
        return csum[i] + frac * prof[np.minimum(i, H - 1)]

    capn = (_integral(hi_e) - _integral(lo_e)) / (hi_e - lo_e)

    def local_offset(idx, half=6, rng=3.0, step=0.25):
        a, bb = runs_nat[idx]
        lo, hi = max(0, a - half), min(h_nat, bb + half)
        T = natprof[lo:hi]
        if T.sum() <= 0 or hi - lo < 6:
            return None, 0.0
        t = T - T.mean()
        tn = float((t * t).sum())
        if tn <= 0:
            return None, 0.0
        best_d, best_r = None, -2.0
        for d in np.arange(-rng, rng + 1e-9, step):
            C = np.interp(np.arange(lo, hi) + d,
                          np.arange(h_nat, dtype=np.float64), capn)
            c = C - C.mean()
            den = np.sqrt(tn * float((c * c).sum()))
            if den <= 0:
                continue
            r = float((t * c).sum() / den)
            if r > best_r:
                best_d, best_r = float(d), r
        return best_d, best_r

    mids = {sl["runs_idx"][1] for sl in page_meta["slots"]}
    anchor_pts = []
    for i in range(len(runs_nat)):
        if i in mids:
            continue
        d, r = local_offset(i)
        if d is not None and r >= 0.4:
            anchor_pts.append((nat[i], d))
    if len(anchor_pts) < 2:
        return {"ok": False, "reason": "too few correlating anchor runs"}
    ay = np.array([y for y, _ in anchor_pts])
    ad = np.array([d for _, d in anchor_pts])

    def anchor_ref(y):
        """Local zero-displacement reference: median of the nearest
        anchors (robust to a stray bad correlation)."""
        idx = np.argsort(np.abs(ay - y))[:5]
        return float(np.median(ad[idx]))

    # Bit = sign of the middle strip's displacement relative to the local
    # anchor reference. Content shifted DOWN (bit 1) sits at larger native
    # rows, so the template T(y) matches capn(y + d) at d = +1: positive
    # deviation means bit 1.
    bits = {}
    for si, slotrec in enumerate(page_meta["slots"]):
        j = slotrec["runs_idx"][1]
        d, r = local_offset(j)
        if d is None or r < 0.3:
            bits[si] = None
        else:
            dev = d - anchor_ref(nat[j])
            # Erasure band: a displacement far below the embedded shift is
            # noise, not signal — abstain rather than coin-flip.
            bits[si] = (None if abs(dev) < 0.35 * SHIFT_PX
                        else (1 if dev > 0 else 0))
    return {"ok": True, "deskew_deg": round(ang, 2),
            "quality": round(quality, 3), "bits": bits}


def score(observed, page_meta):
    """(ok, tot) over slots that were actually shifted in this variant."""
    ok = tot = 0
    for si, slotrec in enumerate(page_meta["slots"]):
        ob = observed["bits"].get(si)
        if ob is None or slotrec["delta_px"] == 0:
            continue
        tot += 1
        ok += int(ob == slotrec["bit"])
    return ok, tot
