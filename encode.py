#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Smoke-test encoder, Carrier 1 only (Brassil-family word-shift + line-shift).

Renders one A4 page at 300 dpi with:
  - line-shift coding: lines in triplets (control, marked, control); the marked
    line's baseline is shifted +/- LINE_SHIFT px. 1 bit per triplet.
  - word-shift coding: interior words of every line shifted +/- WORD_SHIFT px,
    implemented as gap_before += d, gap_after -= d. 1 bit per interior word.

Payload is a fixed PRN bitstream from --seed, embedded with repetition.
Sidecar JSON stores ground truth for scoring only; the decoder is blind.

The layout and rendering live in module-level functions (wrap_words,
render_page) so the local app (app/engine/render.py) shares one source of
truth for the public encoding convention with this CLI. The CLI behavior is
unchanged.

Usage:
  python encode.py --out marked.png --meta meta.json [--seed 42] [--unmarked]
"""
import argparse, json, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DPI = 300
PAGE_W, PAGE_H = 2480, 3508          # A4 at 300 dpi
MARGIN_X, MARGIN_TOP = 260, 300
BOTTOM_MARGIN = 300
FONT_PX = 42                          # ~10 pt at 300 dpi
PITCH = 62                            # nominal baseline pitch, px
GAP = 14                              # nominal inter-word gap, px
WORD_SHIFT = 3                        # +/- px, 1/100 inch at 300 dpi
LINE_SHIFT = 2                        # +/- px, 1/150 inch at 300 dpi
# Fixed serif face for the whole pipeline. Keep this ONE font for every render
# (marked docs, unmarked controls, reprints) so the embedded geometry stays
# self-consistent; the decoder is blind and reads meta written at render time,
# but mixing fonts between a doc and its control would compare different layouts.
# The default face is Liberation Serif, bundled under assets/fonts/ (SIL OFL
# 1.1), so a fresh clone renders identically on every OS with no font setup.
# It is metric-compatible with Times New Roman. Override per-run with --font or
# the FF_FONT_PATH env var for deliberate font experiments. A serif face
# matters: the decoder locates baselines from character-bottom components and
# the shift amplitudes are 2-3 px, which are geometric and font-independent.
_HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED_FONT = os.path.join(_HERE, "assets", "fonts",
                            "LiberationSerif-Regular.ttf")
FONT_PATH = os.environ.get("FF_FONT_PATH") or BUNDLED_FONT

CORPUS = ("the standard model of examination security assumes that custody of "
"printed material can be audited after the fact through physical seals and "
"human testimony alone this assumption fails precisely when the custodian is "
"complicit because the seal reports only that the packet was opened not who "
"photographed the contents once opened a forensic fingerprint embedded in the "
"printed page itself shifts the evidentiary basis from testimony to signal "
"each copy carries an invisible codeword drawn from a collusion resistant "
"code so that any leaked photograph identifies the source unit with a provable "
"bound on the probability of false accusation the marking survives the hostile "
"channel of a phone camera and social media recompression because it is "
"carried by low frequency geometry rather than fine texture the question this "
"experiment answers is whether the physical channel preserves enough of that "
"geometry to be useful at all which is the cheapest possible thing to falsify "
"before any further investment in code design or learned carriers").split()


def prn_bits(seed, count):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2, size=count).tolist()


def load_font(path):
    return ImageFont.truetype(path, FONT_PX)


def make_measure(font):
    """Word-width measure identical to the historical draw.textbbox path."""
    scratch = ImageDraw.Draw(Image.new("L", (4, 4), 255))

    def wwidth(w):
        b = scratch.textbbox((0, 0), w, font=font)
        return b[2] - b[0]
    return wwidth


def max_page_lines():
    """Line count at which the historical wrap loop stops: it appends a line,
    then breaks when MARGIN_TOP + len(lines) * PITCH > PAGE_H - BOTTOM_MARGIN,
    so the first line count PAST the fit rule is kept."""
    fit = (PAGE_H - BOTTOM_MARGIN - MARGIN_TOP) // PITCH
    return fit + 1


def wrap_words(measure, words, drop_overflow_word=False, max_lines=None):
    """Ragged-right wrap of a finite word list into lines.

    drop_overflow_word=True reproduces the historical smoke-test quirk: the
    word that triggers a line break is skipped, not re-queued (invisible with
    the cycling CORPUS, wrong for user content, so the app passes False).
    max_lines, when set, stops at that many lines and discards a trailing
    partial line (also the historical page-fill behavior).
    """
    max_w = PAGE_W - 2 * MARGIN_X
    lines, cur, cur_w = [], [], 0
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        ww = measure(w)
        add = ww if not cur else GAP + ww
        if cur_w + add > max_w and cur:
            lines.append(cur)
            cur, cur_w = [], 0
            if max_lines is not None and len(lines) >= max_lines:
                return lines
            if not drop_overflow_word:
                i -= 1
            continue
        cur.append(w)
        cur_w += add
    if cur:
        lines.append(cur)
    return lines


def slot_indices(n_words):
    """Bit slots: only ALTERNATING interior words carry bits (odd indices),
    because adjacent coded words would share a gap and their shifts cancel
    (intersymbol interference). Buffer words stay unshifted. This exact rule
    is the public convention duplicated inline in decode.py."""
    return [i for i in range(1, n_words - 1) if i % 2 == 1]


def render_page(lines, payload, unmarked, font, keep_partial_triplet=False):
    """Render one page of pre-wrapped lines with the public convention.

    Returns (PIL.Image, meta). By default trims to whole triplets (historical
    CLI behavior). keep_partial_triplet=True renders the 1-2 leftover lines
    as uncoded filler (line_bit None, word_bits all None, no shifts) so user
    content is not dropped; decode.py handles them via the meta.
    """
    img = Image.new("L", (PAGE_W, PAGE_H), 255)
    draw = ImageDraw.Draw(img)

    def wwidth(w):
        b = draw.textbbox((0, 0), w, font=font)
        return b[2] - b[0]

    n_whole = len(lines) - (len(lines) % 3)
    if not keep_partial_triplet:
        lines = lines[:n_whole]
    n_lines = len(lines)

    word_slots = sum(len(slot_indices(len(L))) for L in lines[:n_whole])
    line_slots = n_whole // 3
    P = len(payload)
    word_bits = [payload[i % P] for i in range(word_slots)]
    line_bits = [payload[i % P] for i in range(line_slots)]

    meta = {"payload": payload, "n_lines": n_lines, "pitch": PITCH, "gap": GAP,
            "word_shift": WORD_SHIFT, "line_shift": LINE_SHIFT,
            "unmarked": bool(unmarked), "lines": []}

    wslot = 0
    for li, words in enumerate(lines):
        coded = li < n_whole
        trip_pos = li % 3                        # 0 control, 1 marked, 2 control
        lshift = 0
        lbit = None
        if coded and trip_pos == 1 and not unmarked:
            lbit = line_bits[li // 3]
            lshift = LINE_SHIFT if lbit == 1 else -LINE_SHIFT
        baseline = MARGIN_TOP + li * PITCH + lshift

        # Per-word gap adjustment for word-shift coding (alternating slots).
        gaps = [GAP] * (len(words) - 1)
        wbits = [None] * len(words)
        if coded:
            for widx in slot_indices(len(words)):
                b = word_bits[wslot]
                wbits[widx] = b
                if not unmarked:
                    d = WORD_SHIFT if b == 1 else -WORD_SHIFT
                    gaps[widx - 1] += d
                    gaps[widx] -= d
                wslot += 1

        x = MARGIN_X
        for widx, w in enumerate(words):
            draw.text((x, baseline), w, font=font, fill=0, anchor="ls")
            if widx < len(words) - 1:
                x += wwidth(w) + gaps[widx]

        meta["lines"].append({"line_index": li, "triplet_pos": trip_pos,
                              "line_bit": lbit, "n_words": len(words),
                              "word_bits": wbits})

    return img, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--font", default=FONT_PATH,
                    help="path to a serif .ttf (default: $FF_FONT_PATH or the "
                         "bundled Liberation Serif under assets/fonts/)")
    ap.add_argument("--unmarked", action="store_true",
                    help="render the same layout with zero shifts (control doc)")
    args = ap.parse_args()

    try:
        font = load_font(args.font)
    except OSError:
        ap.error(f"could not load font {args.font!r}; pass --font <path> or set "
                 "FF_FONT_PATH to a serif .ttf")

    # Historical smoke-test layout: cycle CORPUS to fill one page, dropping
    # the word that triggers each line break (see wrap_words docstring).
    measure = make_measure(font)
    cap = max_page_lines()
    stream = [CORPUS[i % len(CORPUS)] for i in range((cap + 2) * 40)]
    lines = wrap_words(measure, stream, drop_overflow_word=True, max_lines=cap)

    PAYLOAD = 64
    payload = prn_bits(args.seed, PAYLOAD)
    img, meta = render_page(lines, payload, args.unmarked, font)

    img.save(args.out, dpi=(DPI, DPI))
    with open(args.meta, "w") as f:
        json.dump(meta, f)
    n_lines = meta["n_lines"]
    line_slots = n_lines // 3
    word_slots = sum(len(slot_indices(l["n_words"])) for l in meta["lines"])
    print(f"encoded {args.out}: {n_lines} lines, {line_slots} line bits, "
          f"{word_slots} word bits, payload {PAYLOAD} bits "
          f"({'UNMARKED CONTROL' if args.unmarked else 'marked'})")


if __name__ == "__main__":
    main()
