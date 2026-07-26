#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pixel-diff evidence for the "nothing changes but the nudges" claim, on a
representative fancy-layout document (doc02_helv_headings: Helvetica body
text with bold section headings).

    python field-test-002/pixel_diff.py

Renders the archived original and marked-v1 PDFs at 300 dpi, computes the
absolute pixel difference, verifies every changed pixel sits inside the
marked lines' own row spans (from the archived meta, never hand-typed),
and writes:
    pixel-diff/diff_doc02_v1.png      gold-on-navy map of changed pixels
    pixel-diff/diff_stats.json        counts + containment verdict
"""
import json
import os
import sys

import fitz
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DPI = 300
SCALE = DPI / 72.0

ORIGINAL = os.path.join(HERE, "print", "doc02_helv_headings__control.pdf")
MARKED = os.path.join(HERE, "print", "doc02_helv_headings__v1.pdf")
META = os.path.join(HERE, "metas", "doc02_helv_headings__v1.json")


def raster(path):
    doc = fitz.open(path)
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(SCALE, SCALE),
                            colorspace=fitz.csGRAY, alpha=False)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height,
                                                     pix.width).copy()
    doc.close()
    return a


def main():
    go, gv = raster(ORIGINAL), raster(MARKED)
    meta = json.load(open(META))
    pg = meta["pages"][0]

    diff = np.abs(go.astype(np.int16) - gv.astype(np.int16)).astype(np.uint8)
    changed = diff > 0

    # Allowed rows: each APPLIED marked line's own span (one pitch tall).
    allowed = np.zeros(go.shape[0], bool)
    marked_lines = []
    for band in pg["bands"]:
        pitch_px = band["pitch_pt"] * SCALE
        for line in band["lines"]:
            if line["role"] == "marked" and line["applied"]:
                y = line["y_px300"]
                lo, hi = int(y - pitch_px), int(y + pitch_px)
                allowed[max(0, lo):min(len(allowed), hi)] = True
                marked_lines.append({"y_px300": y,
                                     "bit": line["bit"],
                                     "text_head": line["text_head"]})

    outside = changed[~allowed]
    stats = {
        "document": os.path.basename(MARKED),
        "page": 0,
        "image_px": [int(go.shape[1]), int(go.shape[0])],
        "total_pixels": int(go.size),
        "changed_pixels": int(changed.sum()),
        "changed_fraction": round(float(changed.sum()) / go.size, 6),
        "marked_lines": len(marked_lines),
        "changed_pixels_outside_marked_rows": int(outside.sum()),
        "containment": bool(outside.sum() == 0),
        "claim": ("every changed pixel lies within a marked line's own row "
                  "span" if outside.sum() == 0 else
                  "CONTAINMENT FAILED, see changed_pixels_outside_marked_rows"),
        "marked_line_details": marked_lines,
    }

    navy = np.array([12, 20, 36], np.uint8)
    gold = np.array([201, 162, 39], np.uint8)
    rgb = np.zeros((*go.shape, 3), np.uint8)
    rgb[:] = navy
    rgb[changed] = gold
    img = Image.fromarray(rgb)
    w = 1400
    img = img.resize((w, round(go.shape[0] * w / go.shape[1])),
                     Image.LANCZOS)
    outdir = os.path.join(HERE, "pixel-diff")
    os.makedirs(outdir, exist_ok=True)
    img.save(os.path.join(outdir, "diff_doc02_v1.png"))
    json.dump(stats, open(os.path.join(outdir, "diff_stats.json"), "w"),
              indent=1)
    print(json.dumps({k: v for k, v in stats.items()
                      if k != "marked_line_details"}, indent=1))
    if not stats["containment"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
