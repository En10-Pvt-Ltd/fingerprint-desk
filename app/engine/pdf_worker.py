# SPDX-License-Identifier: Apache-2.0
"""Subprocess-isolated handling of untrusted PDFs.

pikepdf/PyMuPDF parse attacker-supplied bytes; a crafted PDF that segfaults
the parser must kill a child process, not the server. serve.py invokes this
module (python -m engine.pdf_worker, cwd=app/) with a timeout; the child
caps its own address space via RLIMIT_AS before touching the input.

Commands (result is one JSON object on stdout, {"ok": false, "error": msg}
for expected rejections; a crash simply produces no JSON):

    analyze  <pdf-path>        -> {"ok": true, "extract": {...}, "cap": {...}}
    generate <spec-json-path>  -> {"ok": true, "test_id": ...}
        spec = {name, pdf_path, variant_labels, n_controls, test_id,
                source_filename}
"""
import json
import os
import sys

# RLIMIT_AS ceiling for this child. NOTE: RLIMIT_AS caps VIRTUAL address
# space, not resident memory, and OpenCV/OpenBLAS reserve large virtual
# arenas (per-thread) — the raster/vector carriers peak at ~3.5 GB VIRTUAL
# while using only ~0.5 GB RSS (measured on Linux across 2- to 32-page
# documents). The old 1536 MB ceiling was far below that virtual need and
# SIGSEGV'd the child on Linux (silently, since resource is a no-op on
# Windows). Default sized to the measured peak + headroom; configurable.
MEM_MB = int(os.environ.get("FF_PDF_WORKER_MEM_MB", "4096"))
MEM_BYTES = MEM_MB * 1024 * 1024


def _limit():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEM_BYTES, MEM_BYTES))
    except (ImportError, ValueError, OSError):
        pass                       # Windows has no rlimits; timeout still applies


def _raster_fallback(data, text_error):
    """The text pathways refused this PDF. Try the two no-text carriers in
    turn: raster (scanned/image-only pages) then vector (text converted to
    outline paths). Offer whichever finds markable line strips."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        n_pages = doc.page_count
        doc.close()
    except Exception:
        return {"ok": False, "error": text_error}
    from . import raster_mark, vector_mark
    for mode, mark in (("pdf_raster", raster_mark),
                       ("pdf_vector", vector_mark)):
        try:
            ana = mark.analyze(data, range(min(n_pages, 5)))
            total = sum(len(p["triplets"]) for p in ana)
        except Exception:
            continue
        if ana and total:
            return {"ok": True, "mode": mode,
                    "extract": {"pdf_pages": n_pages},
                    "raster": {"total_bits": total,
                               "pages_marked": len(ana),
                               "per_page": [{"page_index": p["page_index"],
                                             "line_bits": len(p["triplets"])}
                                            for p in ana]}}
    return {"ok": False, "error": text_error + " (The scanned-image and "
            "outline-vector pathways were tried too, but no markable "
            "text-line strips were found on the first pages.)"}


def main():
    _limit()
    cmd = sys.argv[1]
    from . import pdf_source, pdf_mark, render_pdf  # after rlimit

    if cmd == "extract":
        data = open(sys.argv[2], "rb").read()
        try:
            extract = pdf_source.extract_text(data)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return
        print(json.dumps({"ok": True, "extract": extract}))
    elif cmd == "analyze":
        data = open(sys.argv[2], "rb").read()
        try:
            extract = pdf_source.extract_text(data)
            cap = pdf_mark.capacity(data)
        except ValueError as e:
            print(json.dumps(_raster_fallback(data, str(e))))
            return
        print(json.dumps({"ok": True, "mode": "pdf_preserved",
                          "extract": extract, "cap": cap}))
    elif cmd == "generate":
        spec = json.load(open(sys.argv[2], encoding="utf-8"))
        pdf_bytes = open(spec["pdf_path"], "rb").read()
        if spec.get("mode") in ("pdf_raster", "pdf_vector"):
            from . import render_raster
            render_raster.generate_raster_test(
                spec["name"], pdf_bytes, spec["variant_labels"],
                spec["n_controls"], spec["test_id"],
                spec.get("source_filename"), carrier=spec["mode"])
        else:
            render_pdf.generate_pdf_test(spec["name"], pdf_bytes,
                                         spec["variant_labels"],
                                         spec["n_controls"], spec["test_id"],
                                         spec.get("source_filename"))
        print(json.dumps({"ok": True, "test_id": spec["test_id"]}))
    else:
        print(json.dumps({"ok": False, "error": f"unknown command {cmd!r}"}))
        sys.exit(2)


if __name__ == "__main__":
    main()
