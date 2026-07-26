# SPDX-License-Identifier: Apache-2.0
"""Stage 1 PDF content source.

Extracts the text of an uploaded PDF so it can be flowed through the app's
own layout engine. This deliberately does NOT preserve the original
formatting: the encoder must own the layout for the current blind decode
convention (uniform pitch, uniform nominal gaps) to hold. True
formatting-preserving fingerprinting of foreign PDFs is Stage 2
(docs/stage2-pdf-plan.md).
"""
import fitz

MAX_PDF_MB = 25
MIN_CHARS = 40


def extract_text(data: bytes):
    """Return {content, pdf_pages, words} or raise ValueError with a
    user-facing reason."""
    if len(data) > MAX_PDF_MB * 1024 * 1024:
        raise ValueError(f"PDF larger than {MAX_PDF_MB} MB")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise ValueError("not a readable PDF")
    if doc.is_encrypted and not doc.authenticate(""):
        raise ValueError("PDF is password-protected")
    parts = [page.get_text("text") for page in doc]
    n_pages = doc.page_count
    doc.close()
    content = " ".join(" ".join(parts).split())
    if len(content) < MIN_CHARS:
        raise ValueError(
            "no extractable text: this looks like a scanned/image-only PDF. "
            "Per-copy geometry fingerprinting needs text; OCR the document "
            "or paste its text instead.")
    return {"content": content, "pdf_pages": n_pages,
            "words": len(content.split())}
