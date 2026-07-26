# SPDX-License-Identifier: Apache-2.0
"""Sealed-codebook commitment: SHA-256 over the canonical JSON of every
document meta in a test. Computed at generation time; a scan result screen
re-derives it from the metas on disk so the user can watch the envelope
verify. (A production deployment would publish the digest to an append-only
public log; locally the timestamped manifest records it.)
"""
import hashlib
import json


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def codebook_commitment(test_id, doc_metas, pdf_hashes=None):
    """doc_metas: {doc_id: [page_meta, ...]} (or {doc_id: meta} for pdf
    tests). pdf_hashes, when given, binds the emitted variant PDF bytes into
    the commitment too (digitally distributed artifacts must be covered)."""
    payload = {"test_id": test_id, "docs": doc_metas}
    if pdf_hashes:
        payload["pdf_sha256"] = pdf_hashes
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
