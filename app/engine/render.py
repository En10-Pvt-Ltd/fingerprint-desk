# SPDX-License-Identifier: Apache-2.0
"""Multi-page, custom-text rendering built on encode.py's shared functions.

One page of a variant is exactly a smoke-test page: same triplet structure,
same alternating word slots, same shift amplitudes, same meta schema. Custom
text is wrapped once (no word dropping) and paginated into whole-triplet
pages; leftover lines on the last page render as uncoded filler so no user
content is lost.

Seeds follow gen_corpus_docs.py: variant v -> 1000 + v, control c -> 2000 + c.
"""
import hashlib
import json
import os

from . import REPO  # noqa: F401  (sys.path side effect)
import encode
from . import store
from .commitment import codebook_commitment

PAYLOAD_BITS = 64
VARIANT_SEED0 = 1000
CONTROL_SEED0 = 2000
THUMB_W = 360

_font_cache = {}


def get_font(path=None):
    path = path or encode.FONT_PATH
    if path not in _font_cache:
        _font_cache[path] = encode.load_font(path)
    return _font_cache[path]


def page_line_cap():
    """Lines per full page, whole triplets only (45 with the stock metrics)."""
    return (encode.max_page_lines() - 1) // 3 * 3


def paginate(text, font=None):
    """Wrap the full text once and chunk into pages. Returns list of pages
    (each a list of lines) plus layout stats."""
    words = text.split()
    if not words:
        raise ValueError("content is empty")
    measure = encode.make_measure(font or get_font())
    lines = encode.wrap_words(measure, words, drop_overflow_word=False)
    cap = page_line_cap()
    pages = [lines[i:i + cap] for i in range(0, len(lines), cap)]
    return pages, words


def dry_layout(text):
    """Capacity preview for the wizard, without rendering images."""
    pages, words = paginate(text)
    per_page = []
    for chunk in pages:
        whole = len(chunk) - (len(chunk) % 3)
        word_slots = sum(len(encode.slot_indices(len(L)))
                         for L in chunk[:whole])
        per_page.append({"lines": len(chunk), "coded_lines": whole,
                         "line_bits": whole // 3, "word_bits": word_slots})
    return {"words": len(words), "pages": len(pages), "per_page": per_page,
            "payload_bits": PAYLOAD_BITS}


def generate_test(name, text, variant_labels, n_controls, sample_used=False,
                  test_id=None):
    """Render every variant and control, write manifest + commitment.
    Returns the manifest. test_id may be pre-allocated by the server so the
    UI can poll while generation runs in a background thread."""
    font = get_font()
    pages, words = paginate(text, font)
    test_id = test_id or store.new_test_id(name)
    tdir = store.test_dir(test_id)

    docs, doc_metas = [], {}
    specs = [(f"v{i + 1}", label or f"Variant {i + 1}", VARIANT_SEED0 + i + 1,
              True) for i, label in enumerate(variant_labels)]
    specs += [(f"ctrl{c + 1}", f"Control {c + 1}", CONTROL_SEED0 + c + 1,
               False) for c in range(n_controls)]

    for doc_id, label, seed, marked in specs:
        ddir = os.path.join(tdir, "docs", doc_id)
        os.makedirs(ddir, exist_ok=True)
        payload = encode.prn_bits(seed, PAYLOAD_BITS)
        page_records, metas = [], []
        for k, chunk in enumerate(pages):
            img, meta = encode.render_page(chunk, payload, not marked, font,
                                           keep_partial_triplet=True)
            meta.update({"test_id": test_id, "doc_id": doc_id, "seed": seed,
                         "marked": marked, "page_index": k,
                         "n_pages": len(pages)})
            png = os.path.join(ddir, f"page{k}.png")
            img.save(png, dpi=(encode.DPI, encode.DPI))
            w = THUMB_W
            img.resize((w, round(img.height * w / img.width))) \
               .save(os.path.join(ddir, f"page{k}_thumb.png"))
            with open(os.path.join(ddir, f"page{k}_meta.json"), "w") as f:
                json.dump(meta, f)
            whole = meta["n_lines"] - (meta["n_lines"] % 3)
            page_records.append({
                "page_index": k, "n_lines": meta["n_lines"],
                "line_bits": whole // 3,
                "word_bits": sum(len(encode.slot_indices(l["n_words"]))
                                 for l in meta["lines"]
                                 if l["word_bits"] and
                                 any(b is not None for b in l["word_bits"])),
            })
            metas.append(meta)
        docs.append({"doc_id": doc_id, "label": label, "seed": seed,
                     "marked": marked, "pages": page_records})
        doc_metas[doc_id] = metas

    manifest = {
        "test_id": test_id, "name": name, "created_utc": store.now_utc(),
        "status": "generated", "sample_used": bool(sample_used),
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "content_words": len(words), "n_pages": len(pages),
        "docs": docs,
        "commitment": {
            "algo": "sha256(canonical-json of all page metas)",
            "sha256": codebook_commitment(test_id, doc_metas),
            "committed_utc": store.now_utc(),
        },
    }
    store.save_manifest(manifest)
    return manifest


def load_page_meta(test_id, doc_id, page_index):
    p = os.path.join(store.test_dir(test_id), "docs", doc_id,
                     f"page{page_index}_meta.json")
    return json.load(open(p, encoding="utf-8"))


def recompute_commitment(manifest):
    doc_metas = {d["doc_id"]: [load_page_meta(manifest["test_id"], d["doc_id"], k)
                               for k in range(manifest["n_pages"])]
                 for d in manifest["docs"]}
    return codebook_commitment(manifest["test_id"], doc_metas)


# Six passes of the research corpus text: enough words for a two-page test,
# so the sample exercises pagination and page identification.
SAMPLE_TEXT = " ".join(encode.CORPUS * 6)
