# SPDX-License-Identifier: Apache-2.0
"""Generation for formatting-preserved PDF tests (Stage 2 M4).

Each marked variant is the customer's own PDF with invisible line-shifts
injected into its content streams (pdf_mark.embed); controls are byte
copies. Page PNGs are rasterized for the gallery and the simulate-leak
path, and the sealed-codebook commitment binds both the metas AND the
emitted PDF bytes (the variants are distributed digitally, so the envelope
must cover the exact files).
"""
import hashlib
import json
import os

import fitz

from . import store
from . import pdf_mark
from .commitment import codebook_commitment
from .render import VARIANT_SEED0, CONTROL_SEED0, THUMB_W

DPI = 300


def _raster_pages(pdf_bytes, ddir):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for k, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(DPI / 72, DPI / 72),
                              colorspace=fitz.csGRAY, alpha=False)
        pix.save(os.path.join(ddir, f"page{k}.png"))
        s = THUMB_W / pix.width
        page.get_pixmap(matrix=fitz.Matrix(DPI / 72 * s, DPI / 72 * s),
                        colorspace=fitz.csGRAY, alpha=False) \
            .save(os.path.join(ddir, f"page{k}_thumb.png"))
    n = doc.page_count
    doc.close()
    return n


def generate_pdf_test(name, pdf_bytes, variant_labels, n_controls,
                      test_id, source_filename=None):
    tdir = store.test_dir(test_id)
    os.makedirs(tdir, exist_ok=True)
    with open(os.path.join(tdir, "source.pdf"), "wb") as f:
        f.write(pdf_bytes)

    specs = [(f"v{i + 1}", label or f"Variant {i + 1}",
              VARIANT_SEED0 + i + 1, True)
             for i, label in enumerate(variant_labels)]
    specs += [(f"ctrl{c + 1}", f"Control {c + 1}", CONTROL_SEED0 + c + 1,
               False) for c in range(n_controls)]

    docs, doc_metas, pdf_hashes = [], {}, {}
    for doc_id, label, seed, marked in specs:
        ddir = os.path.join(tdir, "docs", doc_id)
        os.makedirs(ddir, exist_ok=True)
        data, meta = pdf_mark.embed(pdf_bytes, seed, unmarked=not marked)
        meta.update({"test_id": test_id, "doc_id": doc_id, "marked": marked})
        with open(os.path.join(ddir, "document.pdf"), "wb") as f:
            f.write(data)
        with open(os.path.join(ddir, "meta.json"), "w") as f:
            json.dump(meta, f)
        _raster_pages(data, ddir)
        pdf_hashes[doc_id] = hashlib.sha256(data).hexdigest()
        pages = []
        for pg in meta["pages"]:
            applied = sum(1 for b in pg["bands"] for l in b["lines"]
                          if l["role"] == "marked" and l["applied"])
            pages.append({"page_index": pg["page_index"],
                          "n_lines": pg["n_lines_total"],
                          "line_bits": applied if marked else
                          sum(1 for b in pg["bands"] for l in b["lines"]
                              if l["role"] == "marked"),
                          "word_bits": 0})
        docs.append({"doc_id": doc_id, "label": label, "seed": seed,
                     "marked": marked, "pages": pages,
                     "pdf_sha256": pdf_hashes[doc_id]})
        doc_metas[doc_id] = meta

    manifest = {
        "test_id": test_id, "name": name, "created_utc": store.now_utc(),
        "status": "generated", "type": "pdf_preserved",
        "source_filename": source_filename,
        "content_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "n_pages": doc_metas["v1"]["n_pages"],
        "docs": docs,
        "commitment": {
            "algo": "sha256(canonical-json of all doc metas + variant "
                    "pdf hashes)",
            "sha256": codebook_commitment(test_id, doc_metas, pdf_hashes),
            "committed_utc": store.now_utc(),
        },
    }
    store.save_manifest(manifest)
    return manifest


def load_doc_meta(test_id, doc_id):
    p = os.path.join(store.test_dir(test_id), "docs", doc_id, "meta.json")
    return json.load(open(p, encoding="utf-8"))


def recompute_commitment(manifest):
    tdir = store.test_dir(manifest["test_id"])
    doc_metas, pdf_hashes = {}, {}
    for d in manifest["docs"]:
        doc_metas[d["doc_id"]] = load_doc_meta(manifest["test_id"],
                                               d["doc_id"])
        pdf = open(os.path.join(tdir, "docs", d["doc_id"], "document.pdf"),
                   "rb").read()
        pdf_hashes[d["doc_id"]] = hashlib.sha256(pdf).hexdigest()
    return codebook_commitment(manifest["test_id"], doc_metas, pdf_hashes)
