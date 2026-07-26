# SPDX-License-Identifier: Apache-2.0
"""Decode a captured image of a pdf_lineshift page (Stage 2 M2+).

Blind at capture time for the geometry (deskew + line segmentation from the
image itself, reusing decode.py), meta-guided for the layout: the meta says
how many text lines the page has and where the markable bands sit in that
top-to-bottom order, so triplet statistics are computed only inside bands
and headings/whitespace never confuse the triplet grid.

Bit convention identical to the research decoder: stat = second difference
of consecutive baselines within a triplet; positive (middle line sits low)
means bit 1.
"""
import os

import cv2
import numpy as np

from . import REPO  # noqa: F401
import decode as dec
from run_robust import crop_to_page, segment_autocorr


def _observe_bands(gray, rows, page_meta):
    baselines = [dec.line_baseline(gray, a, b) for a, b in rows]
    bands = []
    for band in page_meta["bands"]:
        s = band["start_line"]
        n = len(band["lines"])
        n_whole = n - (n % 3)
        bits = []
        for t in range(n_whole // 3):
            i = s + 3 * t + 1
            bp, bm, bn = baselines[i - 1], baselines[i], baselines[i + 1]
            if None in (bp, bm, bn):
                bits.append(None)
            else:
                bits.append(1 if (bm - bp) - (bn - bm) > 0 else 0)
        bands.append(bits)
    return bands


def observe_page(img_path, page_meta):
    """Extract observed triplet bits for every band of one page (clean /
    synthetic captures: no crop or illumination correction needed).

    Returns {"ok": bool, "reason", "deskew_deg", "n_lines_found",
             "bands": [ [bit|None per triplet] per band ]}.
    """
    gray = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return {"ok": False, "reason": "unreadable image"}
    g, ang = dec.deskew(gray)
    rows = dec.segment_lines(g)
    out = {"deskew_deg": round(ang, 2), "n_lines_found": len(rows),
           "path": "clean"}
    if len(rows) != page_meta["n_lines_total"]:
        out.update({"ok": False,
                    "reason": f"segmented {len(rows)} lines, meta says "
                              f"{page_meta['n_lines_total']}"})
        return out
    out.update({"ok": True, "bands": _observe_bands(g, rows, page_meta)})
    return out


def _crop_union(img_path, dst):
    """Shadow-tolerant page crop: union bbox of all substantial bright
    components after closing, so a shadow that splits the page cannot cut
    off its top or bottom (the single-largest-component crop can)."""
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    b = cv2.GaussianBlur(img, (0, 0), 3)
    _, m = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = cv2.morphologyEx((m > 0).astype(np.uint8), cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                   (41, 41)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        cv2.imwrite(dst, cv2.imread(img_path, cv2.IMREAD_COLOR))
        return dst
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = [i + 1 for i, a in enumerate(areas) if a >= 0.2 * areas.max()]
    x0 = min(stats[i, cv2.CC_STAT_LEFT] for i in big)
    y0 = min(stats[i, cv2.CC_STAT_TOP] for i in big)
    x1 = max(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH]
             for i in big)
    y1 = max(stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT]
             for i in big)
    ix, iy = int((x1 - x0) * 0.01), int((y1 - y0) * 0.01)
    crop = cv2.imread(img_path, cv2.IMREAD_COLOR)[y0 + iy:y1 - iy,
                                                  x0 + ix:x1 - ix]
    cv2.imwrite(dst, crop)
    return dst


def _guided_rows(gray, page_meta):
    """Meta-guided line segmentation for real photos of variable-layout
    pages: fit the known line-y pattern (meta line_ys_px300) to the ink row
    profile with a global scale+offset search, then refit each markable
    band's uniform-pitch comb locally (scale + offset around the global
    fit, per-line micro-adjust) so perspective drift and non-text ink
    between blocks cannot break the fit. Returns (rows, diag) where diag
    carries the fit validity metrics (quality of ink at predicted band-line
    centers, scale sanity, valley contrast inside bands) used to reject
    foreign documents."""
    ys = page_meta.get("line_ys_px300")
    if not ys or len(ys) < 2:
        return None, {"quality": 0.0}
    ys = np.asarray(ys, dtype=np.float64)
    H = gray.shape[0]
    ink = (255.0 - gray.astype(np.float64)).sum(axis=1)
    prof = np.convolve(ink, np.ones(5) / 5.0, mode="same")

    page_h_px = page_meta["height_pt"] / 72.0 * 300.0
    s0 = H / page_h_px
    best = (None, -1.0)
    for s in np.linspace(0.55 * s0, 1.45 * s0, 91):
        r = ys * s
        span = r[-1] - r[0]
        if span >= H:
            continue
        for b in np.linspace(-r[0], H - 1 - r[-1], 41):
            idx = np.clip((r + b).astype(int), 0, H - 1)
            sc = float(prof[idx].sum())
            if sc > best[1]:
                best = ((s, b), sc)
    if best[0] is None:
        return None, {"quality": 0.0}
    s, b = best[0]

    # Band-local comb refinement. Sequential line-to-line tracking is
    # fragile on mixed-content pages: crossing a graphics zone (image,
    # table rules, vector art) it can re-lock one line off and drag the
    # whole tail with it. Bands are internally uniform-pitch by
    # construction, so each band's line pattern is refit as a rigid comb
    # (local scale + offset around the global fit), then each line is
    # micro-adjusted within a fraction of the band pitch. Graphics between
    # bands never enter a band's fit window.
    bands = [list(range(bd["start_line"], bd["start_line"] + len(bd["lines"])))
             for bd in (page_meta.get("bands") or [])]
    band_idx = sorted({i for bi in bands for i in bi
                       if 0 <= i < len(ys)})
    if not band_idx:
        return None, {"quality": 0.0}      # nothing markable to observe

    med_pitch = float(np.median(np.diff(ys)))
    centers = ys * s + b
    for bi in bands:
        bi = [i for i in bi if 0 <= i < len(ys)]
        if not bi:
            continue
        by = ys[bi]
        pitch = float(np.median(np.diff(by))) if len(by) > 1 else med_pitch
        base = by[0] * s + b
        best_local = ((s, 0.0), -1.0)
        for ls in np.linspace(0.94 * s, 1.06 * s, 13):
            rel = (by - by[0]) * ls
            for lb in np.linspace(-1.5 * pitch * s, 1.5 * pitch * s, 61):
                idx = np.clip((base + lb + rel).astype(int), 0, H - 1)
                sc = float(prof[idx].sum())
                if sc > best_local[1]:
                    best_local = ((ls, lb), sc)
        ls, lb = best_local[0]
        pos = base + lb + (by - by[0]) * ls
        w = max(2, int(0.22 * ls * pitch))
        for k, i in enumerate(bi):
            lo = max(0, int(pos[k]) - w)
            hi = min(H, int(pos[k]) + w + 1)
            centers[i] = (lo + int(np.argmax(prof[lo:hi]))
                          if hi > lo else pos[k])

    cint, prev = [], None
    for c in centers:
        c = int(round(float(c)))
        if prev is not None and c <= prev:
            c = prev + 1
        cint.append(min(H - 1, max(0, c)))
        prev = cint[-1]
    centers = np.asarray(cint)

    # Validity is judged on the lines that carry bits: band lines. Titles,
    # table rows and other non-band lines exist in the meta only to keep
    # the top-to-bottom line order; pages with graphics put ink between
    # THOSE lines, not between band lines, so gating on all lines would
    # reject exactly the mixed-content pages the guided path exists for.
    # Valleys likewise only count between consecutive lines of one band.
    keep = [i for i in band_idx if 0 <= i < len(centers)]
    kc = centers[keep] if keep else centers
    ref = float(np.median(prof[kc]))
    quality = float(np.mean(prof[kc] > 0.15 * ref)) if ref > 0 else 0.0
    mids = ((centers[:-1] + centers[1:]) // 2)      # row boundaries: all
    if band_idx:
        vmids = np.asarray([(centers[i] + centers[i + 1]) // 2
                            for i, j in zip(keep, keep[1:]) if j == i + 1],
                           dtype=int)
    else:
        vmids = mids
    valley_ratio = (float(np.median(prof[vmids]) / ref)
                    if ref > 0 and len(vmids) else 1.0)
    diag = {"quality": round(quality, 3),
            "scale_ratio": round(s / s0, 3),
            "valley_ratio": round(valley_ratio, 3)}
    bnds = [max(0, int(centers[0] - 0.5 * s * (ys[1] - ys[0])))]
    bnds += [int(m) for m in mids]
    bnds.append(min(H, int(centers[-1] + 0.5 * s * (ys[-1] - ys[-2]))))
    rows = [(bnds[i], bnds[i + 1]) for i in range(len(centers))]
    # Tighten each row to the ink run nearest its tracked center:
    # line_baseline pads its band by a quarter of the band height, which on
    # these wide gap-to-gap rows can reach the neighboring line's glyph
    # bottoms — clipped into many tiny components, they hijack the median
    # height filter and drag the baseline to the band edge. And a band-edge
    # row whose boundary crosses a graphics zone must not absorb that ink,
    # so of the contiguous ink runs inside the row, keep the one containing
    # (or closest to) the line's center. Tight rows (like segment_lines
    # emits) keep the pad inside whitespace.
    tight = []
    for (a, bnd), c in zip(rows, centers):
        seg = (gray[a:bnd] < 128).sum(axis=1) >= 2
        runs = []
        r0 = None
        for k, on in enumerate(seg):
            if on and r0 is None:
                r0 = k
            elif not on and r0 is not None:
                runs.append((r0, k))
                r0 = None
        if r0 is not None:
            runs.append((r0, len(seg)))
        if runs:
            cr = c - a
            r0, r1 = min(runs, key=lambda r: 0 if r[0] <= cr < r[1]
                         else min(abs(cr - r[0]), abs(cr - (r[1] - 1))))
            tight.append((a + r0, a + r1))
        else:
            tight.append((a, bnd))
    return tight, diag


GUIDED_MIN_QUALITY = 0.9
GUIDED_SCALE_BAND = (0.70, 1.35)     # fitted scale vs nominal page fill
GUIDED_MAX_VALLEY = 0.55             # inter-line valleys must exist


def _guided_ok(diag):
    return (diag.get("quality", 0) >= GUIDED_MIN_QUALITY
            and GUIDED_SCALE_BAND[0] <= diag.get("scale_ratio", 0)
            <= GUIDED_SCALE_BAND[1]
            and diag.get("valley_ratio", 1.0) <= GUIDED_MAX_VALLEY)


def observe_page_robust(img_path, page_meta, workdir):
    """Real-photograph path. Ladder over two page crops (single-component,
    then the shadow-tolerant union crop) and three segmenters (adaptive
    threshold, autocorrelation pitch, meta-guided pattern fit). The first
    combination whose line structure matches the meta and passes validity
    wins; every attempt's counts land in the failure reason otherwise."""
    os.makedirs(workdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(img_path))[0]
    want = page_meta["n_lines_total"]
    counts = {}
    ang = None
    for cname, cropf in (("crop1", crop_to_page), ("cropU", _crop_union)):
        cropped = cropf(img_path,
                        os.path.join(workdir, f"{stem}_{cname}.jpg"),
                        **({"verbose": False} if cropf is crop_to_page
                           else {}))
        g0 = cv2.imread(cropped, cv2.IMREAD_GRAYSCALE)
        if g0 is None:
            return {"ok": False, "reason": "unreadable image"}
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
        bg = cv2.morphologyEx(g0, cv2.MORPH_CLOSE, kern)
        norm = np.clip(g0.astype(np.float64) / np.maximum(bg, 1) * 255,
                       0, 255).astype(np.uint8)
        g, ang = dec.deskew(norm)
        for name, segf in (("threshold", dec.segment_lines),
                           ("autocorr", segment_autocorr)):
            rows = segf(g)
            counts[f"{cname}.{name}"] = len(rows)
            if len(rows) == want:
                return {"ok": True, "deskew_deg": round(ang, 2),
                        "n_lines_found": len(rows),
                        "path": f"robust+{cname}.{name}",
                        "bands": _observe_bands(g, rows, page_meta)}
        rows, diag = _guided_rows(g, page_meta)
        counts[f"{cname}.guided"] = diag
        if rows is not None and _guided_ok(diag):
            return {"ok": True, "deskew_deg": round(ang, 2),
                    "n_lines_found": len(rows),
                    "path": f"robust+{cname}.guided",
                    "bands": _observe_bands(g, rows, page_meta)}
    return {"ok": False,
            "deskew_deg": round(ang, 2) if ang is not None else None,
            "n_lines_found": counts, "path": "robust",
            "reason": f"no segmenter matched the meta's {want}-line "
                      f"structure (attempts: {counts}); wrong document, "
                      "wrong page, or too-degraded capture"}


def score_page(observed_bands, variant_page_meta):
    """Compare observed triplet bits against one variant's ground truth.
    Only marked lines whose stream edit was actually applied count."""
    ok = tot = 0
    for bits, band in zip(observed_bands, variant_page_meta["bands"]):
        n_whole = len(band["lines"]) - (len(band["lines"]) % 3)
        for t, ob in enumerate(bits):
            line = band["lines"][3 * t + 1]
            if ob is None or line["role"] != "marked" \
               or not line["applied"] or line["bit"] is None:
                continue
            tot += 1
            ok += int(ob == line["bit"])
    return ok, tot
