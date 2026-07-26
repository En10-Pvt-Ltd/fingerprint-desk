# SPDX-License-Identifier: Apache-2.0
"""Generation for raster (image-only / scanned PDF) tests.

Same product shape as render_pdf.generate_pdf_test, but the carrier is
raster_mark: whole text-line pixel strips of the page image are nudged
+/-2 px in the public triplet convention. Controls are byte copies of the
source. The sealed commitment binds metas AND emitted PDF bytes, exactly
like the preserved pathway, so /verify works unchanged.
"""
import hashlib
import json
import os

import fitz

from . import store
from . import raster_mark
from . import vector_mark
from .commitment import codebook_commitment
from .render import VARIANT_SEED0, CONTROL_SEED0
from .render_pdf import _raster_pages

# Both no-text carriers share this generator: the meta schema and file
# layout are identical, only the embedder differs.
CARRIERS = {"pdf_raster": raster_mark, "pdf_vector": vector_mark}


def generate_raster_test(name, pdf_bytes, variant_labels, n_controls,
                         test_id, source_filename=None,
                         carrier="pdf_raster"):
    mark = CARRIERS[carrier]
    tdir = store.test_dir(test_id)
    os.makedirs(tdir, exist_ok=True)
    with open(os.path.join(tdir, "source.pdf"), "wb") as f:
        f.write(pdf_bytes)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n_pages = doc.page_count
    doc.close()

    specs = [(f"v{i + 1}", label or f"Variant {i + 1}",
              VARIANT_SEED0 + i + 1, True)
             for i, label in enumerate(variant_labels)]
    specs += [(f"ctrl{c + 1}", f"Control {c + 1}", CONTROL_SEED0 + c + 1,
               False) for c in range(n_controls)]

    docs, doc_metas, pdf_hashes = [], {}, {}
    for doc_id, label, seed, marked in specs:
        ddir = os.path.join(tdir, "docs", doc_id)
        os.makedirs(ddir, exist_ok=True)
        data, meta = mark.embed(pdf_bytes, seed, unmarked=not marked)
        meta.update({"test_id": test_id, "doc_id": doc_id, "marked": marked,
                     "n_pages": n_pages})
        with open(os.path.join(ddir, "document.pdf"), "wb") as f:
            f.write(data)
        with open(os.path.join(ddir, "meta.json"), "w") as f:
            json.dump(meta, f)
        _raster_pages(data, ddir)
        pdf_hashes[doc_id] = hashlib.sha256(data).hexdigest()
        pages = [{"page_index": pg["page_index"],
                  "n_lines": len(pg["runs"]),
                  "line_bits": len(pg["slots"]), "word_bits": 0}
                 for pg in meta["pages"]]
        docs.append({"doc_id": doc_id, "label": label, "seed": seed,
                     "marked": marked, "pages": pages,
                     "pdf_sha256": pdf_hashes[doc_id]})
        doc_metas[doc_id] = meta

    # Zero-capacity guard: if no marked doc embedded a single slot, every
    # "marked" PDF is a byte copy of the source and the test would be
    # forensically worthless — fail the generation instead of reporting a
    # generated test that can never attribute anything.
    marked_slots = sum(doc_metas[d["doc_id"]].get("n_slots", 0)
                       for d in docs if d["marked"])
    if marked_slots == 0:
        raise RuntimeError(
            f"the {carrier} carrier found no markable text-line strips in "
            "this document (0 slots embedded); the marked copies would be "
            "identical to the source. This document does not fit this "
            "carrier — re-run the PDF analysis instead of forcing a mode.")

    manifest = {
        "test_id": test_id, "name": name, "created_utc": store.now_utc(),
        "status": "generated", "type": carrier,
        "source_filename": source_filename,
        "content_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "n_pages": n_pages,
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
