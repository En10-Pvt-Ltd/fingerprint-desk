# SPDX-License-Identifier: Apache-2.0
"""Per-campaign recovery key: a single self-contained artifact that carries
everything needed to decode a leaked photo and attribute it to a named
recipient on a *different* installation, with no other data-directory files.

What travels: the codebook (every copy's ground-truth metas, verbatim as
committed), the who-received-which mapping (keyed to a portable identity, never
a local row id), and the commitment digests. What does NOT travel: the document
itself or the distributed PDF bytes -- attribution is blind, so the paper is not
needed, and a leaked key therefore exposes the who-to-which mapping but never
the paper (a deliberate confidentiality property; see docs/recovery-key-format.md).

Step 2 emits the envelope in the clear (encryption is added in step 3). The
`encryption` field is reserved now so the format does not change when it lands.

Seal kind (see docs/threat-model.md):
  - "pre-distribution": the recipient mapping was fixed and bound BEFORE any
    copy was distributed. Proves the mapping predates the leak. Requires a
    roster fixed at creation -- the Phase 4 feature -- so it is NOT reachable
    yet: assignments are currently made on join (first-come-first-served), so
    there is no pre-distribution roster to bind.
  - "snapshot": the mapping as it stood when the key/receipt was made. Proves
    who held which copy at that moment, not that it predates distribution. This
    is the only seal a campaign can carry today.
"""
import hashlib

from . import store, db, render, render_pdf
from .commitment import (canonical, codebook_commitment, keyed_commitment,
                         canonical_assignments, SEAL_SNAPSHOT,
                         SEAL_PREDISTRIBUTION)

FORMAT = "fingerprint-desk-recovery-key"
FORMAT_VERSION = 1
SPEC_DOC = "docs/recovery-key-format.md"

_PDF_TYPES = ("pdf_preserved", "pdf_raster", "pdf_vector")

SEAL_EXPLAIN = {
    SEAL_PREDISTRIBUTION:
        "Proves the recipient mapping was fixed before any copy was "
        "distributed, so it cannot have been altered after a leak appeared.",
    SEAL_SNAPSHOT:
        "Proves the recipient mapping as it stood when this was made. It does "
        "NOT prove the mapping predates distribution -- a 'pre-distribution' "
        "seal (which does) needs a roster fixed at creation and is not "
        "available for campaigns created before that feature exists.",
}


def _is_pdf(m):
    return m.get("type") in _PDF_TYPES


def _load_copies(test_id, m):
    """The per-copy ground-truth metas, keyed by doc_id, in the exact shape the
    commitment hashes: {doc_id: [page_meta,...]} for rendered text, or
    {doc_id: meta} for PDF carriers. Loaded verbatim so the key reproduces the
    sealed codebook digest byte-for-byte."""
    if _is_pdf(m):
        return {d["doc_id"]: render_pdf.load_doc_meta(test_id, d["doc_id"])
                for d in m["docs"]}
    return {d["doc_id"]: [render.load_page_meta(test_id, d["doc_id"], k)
                          for k in range(m["n_pages"])]
            for d in m["docs"]}


def current_seal(test_id, m):
    """The seal kind this campaign can honestly carry right now. Until a
    pre-distribution roster exists (Phase 4), every mapping is a snapshot."""
    return SEAL_SNAPSHOT


def _assemble(test_id, m):
    """Shared core for the envelope, receipt, and info: returns
    (copies, pdf_hashes, assignments, codebook_sha256, keyed_sha256, seal)."""
    if m.get("type") == "pack":
        raise ValueError("recovery keys are for standard campaigns, not "
                         "volunteer-pack tests")
    copies = _load_copies(test_id, m)
    pdf_hashes = ({d["doc_id"]: d["pdf_sha256"] for d in m["docs"]}
                  if _is_pdf(m) else None)
    codebook = codebook_commitment(test_id, copies, pdf_hashes)
    sealed = m["commitment"].get("codebook_sha256") or m["commitment"]["sha256"]
    if codebook != sealed:
        # The metas on disk no longer reproduce the sealed digest: refuse to
        # export a key that would not verify, rather than ship a broken one.
        raise ValueError("codebook digest does not match the sealed commitment; "
                         "campaign data may be corrupted -- not exporting")
    rows = db.assignment_rows(test_id)
    assignments = canonical_assignments(
        [(r["doc_id"], r["email"], r["assigned_utc"]) for r in rows])
    seal = current_seal(test_id, m)
    keyed = keyed_commitment(test_id, codebook, assignments, seal)
    return copies, pdf_hashes, assignments, codebook, keyed, seal


def build_envelope(test_id, m):
    """The full recovery-key artifact (a JSON-serialisable dict). Plaintext in
    step 2; the `encryption` field is reserved for step 3."""
    copies, _pdf, assignments, codebook, keyed, seal = _assemble(test_id, m)
    payload = {
        "test_id": test_id,
        "manifest": m,                 # the codebook index, verbatim
        "copies": copies,              # per-copy ground-truth metas, verbatim
        "assignments": assignments,    # who-received-which, portable identity
        "mapping_seal": seal,
    }
    return {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "campaign_id": test_id,
        "campaign_label": m.get("name"),
        "carrier_type": m.get("type", "rendered"),
        "created_utc": m.get("created_utc"),
        "exported_utc": store.now_utc(),
        "n_marked": sum(1 for d in m["docs"] if d.get("marked")),
        "n_controls": sum(1 for d in m["docs"] if not d.get("marked")),
        "n_recipients": len(assignments),
        "commitment": {
            "codebook_sha256": codebook,
            "keyed_sha256": keyed,
            "mapping_seal": seal,
            "algo": m["commitment"].get("algo"),
            "committed_utc": m["commitment"].get("committed_utc"),
        },
        "encryption": None,            # reserved (step 3: Argon2id + AEAD)
        "payload_sha256": hashlib.sha256(
            canonical(payload).encode("utf-8")).hexdigest(),
        "payload": payload,
    }


def recovery_info(test_id, m):
    """Lightweight metadata for the export UI: seal kind in plain language,
    counts, and the digests -- without serving the ground-truth payload."""
    _c, _p, assignments, codebook, keyed, seal = _assemble(test_id, m)
    return {
        "campaign_id": test_id,
        "campaign_label": m.get("name"),
        "carrier_type": m.get("type", "rendered"),
        "n_marked": sum(1 for d in m["docs"] if d.get("marked")),
        "n_controls": sum(1 for d in m["docs"] if not d.get("marked")),
        "n_recipients": len(assignments),
        "mapping_seal": seal,
        "seal_explain": SEAL_EXPLAIN[seal],
        "codebook_sha256": codebook,
        "keyed_sha256": keyed,
        "committed_utc": m["commitment"].get("committed_utc"),
    }


def build_receipt(test_id, m):
    """A small, self-explanatory commitment receipt: fits in an email or one
    printed page. It carries the digests and the seal kind -- deposit it with a
    third party BEFORE distributing copies so an accusation is checkable
    without trusting the issuer. It contains no ground truth."""
    _c, _p, assignments, codebook, keyed, seal = _assemble(test_id, m)
    seal_line = ("PRE-DISTRIBUTION (proves the mapping predates distribution)"
                 if seal == SEAL_PREDISTRIBUTION
                 else "SNAPSHOT (proves the mapping as it stood when this "
                      "receipt was made -- NOT that it predates distribution)")
    L = [
        "FINGERPRINT DESK - COMMITMENT RECEIPT",
        "=====================================",
        "",
        "What this is: a cryptographic receipt for a fingerprinted-document",
        "campaign. It lets anyone verify later - without trusting the issuer -",
        "that the invisible per-copy codebook, and the record of who received",
        "which copy, existed at the time below and have not been altered since.",
        "It contains no copy of the document itself.",
        "",
        f"Campaign:       {m.get('name')}",
        f"Campaign ID:    {test_id}",
        f"Carrier:        {m.get('type', 'rendered')}",
        f"Copies:         {sum(1 for d in m['docs'] if d.get('marked'))} marked "
        f"+ {sum(1 for d in m['docs'] if not d.get('marked'))} control",
        f"Recipients:     {len(assignments)} recorded",
        f"Sealed (UTC):   {m['commitment'].get('committed_utc')}",
        f"Receipt (UTC):  {store.now_utc()}",
        "",
        "Codebook commitment (SHA-256) - which mark each copy carries:",
        f"  {codebook}",
        "Keyed commitment (SHA-256) - codebook + who-received-which mapping:",
        f"  {keyed}",
        "",
        f"MAPPING SEAL:   {seal_line}",
        "",
        "How to verify: recompute the codebook commitment from the recovery",
        "key's copy metadata using the recipe in " + SPEC_DOC + " and compare",
        "it to the value above. Deposit this receipt with a third party",
        "(counsel, a timestamping service, or an append-only log) BEFORE you",
        "distribute copies: a receipt held off the issuing machine, dated",
        "before any leak, is what makes an accusation checkable rather than",
        "a matter of trusting the operator's disk.",
        "",
        "Fingerprint Desk - https://github.com/En10-Pvt-Ltd/fingerprint-desk",
        "",
    ]
    return "\n".join(L)
