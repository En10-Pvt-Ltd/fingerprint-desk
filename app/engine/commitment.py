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
    the commitment too (digitally distributed artifacts must be covered).

    This is the codebook (v1) commitment: it binds WHICH mark each copy
    carries, and is sealed at generation, before distribution. It says nothing
    about WHO received which copy -- that mapping is bound separately by
    keyed_commitment() below."""
    payload = {"test_id": test_id, "docs": doc_metas}
    if pdf_hashes:
        payload["pdf_sha256"] = pdf_hashes
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


# ---- keyed (v2) commitment: also bind who-received-which -----------------------
# The seal kind is bound INTO the keyed digest, so a point-in-time snapshot can
# never be misrepresented later as a complete pre-distribution seal. See
# docs/recovery-key-format.md (third-party verification contract).
SEAL_PREDISTRIBUTION = "pre-distribution"  # roster fixed + bound BEFORE any copy shipped
SEAL_SNAPSHOT = "snapshot"                 # mapping bound at a point in time after shipping


def canonical_assignments(entries):
    """Canonical, portable form of the who-received-which mapping, sorted so
    the digest is reproducible on any machine and by any third party.

    entries: iterable of (doc_id, recipient, assigned_utc). `recipient` MUST be
    a STABLE, installation-independent identity -- a normalised email, or a
    roster label for an accountless recipient -- NEVER a local database row id,
    which differs between installs and would make the digest unreproducible.
    Returns a list of {doc_id, recipient, assigned_utc} dicts sorted by doc_id.
    The list order is fixed here because canonical() sorts dict keys but
    preserves list order."""
    out = [{"doc_id": doc_id,
            "recipient": (recipient or "").strip().lower(),
            "assigned_utc": assigned_utc}
           for doc_id, recipient, assigned_utc in entries]
    out.sort(key=lambda e: e["doc_id"])
    return out


def keyed_commitment(test_id, codebook_sha256, assignments, mapping_seal):
    """Extend the codebook commitment to also bind the who-received-which
    mapping, so an exported or escrowed mapping is tamper-evident.

    Layered on the codebook digest (which already binds test_id + every copy's
    ground truth + any variant-PDF hashes): the keyed digest is SHA-256 over the
    canonical JSON of {commitment_version, test_id, codebook_sha256,
    assignments, mapping_seal}. `assignments` MUST come from
    canonical_assignments(); `mapping_seal` is SEAL_PREDISTRIBUTION or
    SEAL_SNAPSHOT. Reproducible from the key alone by anyone applying canonical()
    (recursive sort_keys, separators=(",",":"), UTF-8)."""
    payload = {"commitment_version": 2,
               "test_id": test_id,
               "codebook_sha256": codebook_sha256,
               "assignments": assignments,
               "mapping_seal": mapping_seal}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
