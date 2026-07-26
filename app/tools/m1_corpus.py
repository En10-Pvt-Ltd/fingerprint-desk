#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""M1 corpus: ten varied text PDFs for the formatting-preserving embedding
round-trip. Synthesized deterministically, but varied where it matters:
fonts, sizes, leadings, headings, lists, justification, sparse pages,
superscripts (complex-line exclusion), and two documents whose content
streams use relative positioning (Td chains, TL/T*/' operators) that
PyMuPDF-generated PDFs never exercise.

    python app/tools/m1_corpus.py [--out appdata/m1/corpus]
"""
import argparse
import os
import sys

import fitz
import pikepdf

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
import encode  # noqa: E402

WORDS = encode.CORPUS * 30
A4 = (595, 842)
MX, TOP, BOT = 72, 72, 72


def take(n, start=0):
    return WORDS[start % len(WORDS):][:n]


def para(nwords, start=0):
    return " ".join(take(nwords, start))


def wrap(words, fontname, size, width):
    """Greedy wrap by measured width (fitz base-14 metrics)."""
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if fitz.get_text_length(trial, fontname, size) > width and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def fitz_lines_doc(path, fontname, size, leading, n_lines, headings=False,
                   lists=False, superscripts=False, pages=1):
    doc = fitz.open()
    wi = 0
    for _ in range(pages):
        page = doc.new_page(width=A4[0], height=A4[1])
        y = TOP + size
        k = 0
        while y < A4[1] - BOT and k < n_lines:
            if headings and k % 9 == 0:
                page.insert_text((MX, y), f"Section {k // 9 + 1}",
                                 fontname="hebo", fontsize=size + 3)
                y += (size + 3) * leading
                k += 1
                continue
            indent = MX + (14 if lists and (k // 4) % 2 else 0)
            words = take(9, wi)
            wi += 9
            text = ("- " if lists and (k // 4) % 2 else "") + " ".join(words)
            page.insert_text((indent, y), text, fontname=fontname,
                             fontsize=size)
            if superscripts and k % 5 == 2:
                w = fitz.get_text_length(text, fontname, size)
                page.insert_text((indent + w + 2, y - size * 0.35), "42",
                                 fontname=fontname, fontsize=size * 0.6)
            y += size * leading
            k += 1
    doc.save(path)
    doc.close()


def fitz_textbox_doc(path, fontname, size, align):
    doc = fitz.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    rect = fitz.Rect(MX, TOP, A4[0] - MX, A4[1] - BOT)
    page.insert_textbox(rect, para(420), fontname=fontname, fontsize=size,
                        align=align)
    doc.save(path)
    doc.close()


def raw_stream_doc(path, mode):
    """Hand-built content stream with relative positioning. mode='td' uses
    Td chains; mode='tstar' uses TL + T* and the ' (move-and-show) op."""
    size, pitch = 11, 14.5
    width = A4[0] - 2 * MX
    lines = wrap(take(320), "helv", size, width)[:44]
    y0 = A4[1] - TOP - size
    ops = [b"BT", b"/F1 11 Tf"]
    if mode == "td":
        ops.append(f"{MX} {y0:.2f} Td".encode())
        for i, ln in enumerate(lines):
            if i:
                ops.append(f"0 {-pitch:.2f} Td".encode())
            ops.append(b"(" + pdf_escape(ln) + b") Tj")
    else:
        ops.append(f"{pitch:.2f} TL".encode())
        ops.append(f"{MX} {y0:.2f} Td".encode())
        for i, ln in enumerate(lines):
            if i == 0:
                ops.append(b"(" + pdf_escape(ln) + b") Tj")
            elif i % 7 == 3:                      # exercise the ' operator
                ops.append(b"(" + pdf_escape(ln) + b") '")
            else:
                ops.append(b"T*")
                ops.append(b"(" + pdf_escape(ln) + b") Tj")
    ops.append(b"ET")
    stream = b"\n".join(ops)

    pdf = pikepdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=[0, 0, A4[0], A4[1]],
        Resources=pikepdf.Dictionary(
            Font=pikepdf.Dictionary(
                F1=pikepdf.Dictionary(Type=pikepdf.Name.Font,
                                      Subtype=pikepdf.Name.Type1,
                                      BaseFont=pikepdf.Name.Helvetica))),
        Contents=pdf.make_stream(stream))
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))
    pdf.save(path)
    pdf.close()


def pdf_escape(s):
    return s.encode("latin-1", "replace") \
            .replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


DOCS = [
    ("doc01_times11", lambda p: fitz_lines_doc(p, "tiro", 11, 1.35, 44, pages=2)),
    ("doc02_helv_headings", lambda p: fitz_lines_doc(p, "helv", 10, 1.4, 46,
                                                     headings=True)),
    ("doc03_courier12", lambda p: fitz_lines_doc(p, "cour", 12, 1.6, 34)),
    ("doc04_tight9", lambda p: fitz_lines_doc(p, "tiro", 9, 1.12, 60)),
    ("doc05_justified", lambda p: fitz_textbox_doc(p, "tiro", 11,
                                                   fitz.TEXT_ALIGN_JUSTIFY)),
    ("doc06_lists", lambda p: fitz_lines_doc(p, "helv", 10.5, 1.35, 44,
                                             lists=True)),
    ("doc07_sparse", lambda p: fitz_lines_doc(p, "tiro", 12, 1.5, 9)),
    ("doc08_superscript", lambda p: fitz_lines_doc(p, "tiro", 11, 1.35, 40,
                                                   superscripts=True)),
    ("doc09_td_chain", lambda p: raw_stream_doc(p, "td")),
    ("doc10_tstar_quote", lambda p: raw_stream_doc(p, "tstar")),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "appdata", "m1",
                                                  "corpus"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for name, build in DOCS:
        path = os.path.join(args.out, name + ".pdf")
        build(path)
        print("built", path)


if __name__ == "__main__":
    main()
