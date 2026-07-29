# Recovery key & commitment receipt — file format

This is the third-party contract for the two artifacts Fingerprint Desk can export for a
campaign: the **recovery key** (`<campaign>.fdkey.json`) and the **commitment receipt**
(`<campaign>-receipt.txt`). It is written so an auditor, opposing expert, or independent tool
can parse a key and **recompute its commitments from scratch**, without running this software.

For what these prove in an adversarial/legal setting, see
[threat-model.md](threat-model.md); this file is the byte-level format behind that claim.

## What the recovery key is (and is not)

A recovery key carries everything needed to **decode a leaked photo and attribute it to the
named recipient on a different machine**, with no other files from the originating install:
the per-copy ground truth (the codebook), the who-received-which mapping, and the commitment
digests.

It deliberately does **not** contain the document. Attribution is blind — the decoder recovers
the mark from the leaked photo alone — so the paper is never needed. A consequence worth
stating plainly: **a leaked recovery key exposes which copy went to which recipient, but never
the document itself.** The key lets you *re-trace* a leak; it cannot *re-issue* copies. That is
a permanent scope decision, not a limitation to be lifted later.

## The two seal kinds (read this before relying on a mapping in court)

The codebook commitment — *which invisible mark each copy carries* — is always sealed at
generation, before any copy is distributed. The **mapping** commitment — *who received which
copy* — carries one of two seal kinds, and they prove different things:

| `mapping_seal`      | What it proves |
|---------------------|----------------|
| `pre-distribution`  | The recipient mapping was fixed and bound **before any copy was distributed** — so it provably predates any leak. |
| `snapshot`          | The recipient mapping **as it stood when the key/receipt was made**. Proves who held which copy at that moment; it does **not** prove the mapping predates distribution. |

**Which campaigns get which seal:**

- **Roster campaigns** — created from a fixed roster (an explicit list/CSV of recipients) or a
  count pattern — bind the copy→recipient mapping at creation, before any copy is distributed,
  and seal **`pre-distribution`**. The key header records `roster_mode` (`"roster"` | `"count"`).
- **Join campaigns** — where contributors claim copies over time (first-come-first-served) —
  cannot know the mapping until people join, so the mapping bound at export can only be a
  **`snapshot`**. Treat a snapshot as corroborating, not as proof the recipient link predates
  the leak.

The seal kind is bound *into* the keyed digest (below), so a `snapshot` can never be
misrepresented as a `pre-distribution` seal.

**Count-mode rosters — one unsealed link.** A `roster`-mode campaign binds copy→*real
recipient* (the name/email you supplied). A `count`-mode campaign binds copy→*generated label*
(e.g. `Centre-1`); the map from that label to a real centre lives in the issuer's own record
and is **not** covered by this commitment — `roster_mode: "count"` in the header marks exactly
this. Both are `pre-distribution` (the mapping is genuinely fixed at creation), but the count
form has one link a third party must take on the issuer's word.

## Canonicalisation (the one rule everything depends on)

Every digest is `SHA-256` over **canonical JSON**, defined as:

```
canonical(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

That is: object keys sorted recursively at every level, no insignificant whitespace, compact
`,`/`:` separators, UTF-8. **Array order is preserved** (only object keys are sorted), so any
list that must be reproducible is pre-sorted by the producer (see `assignments`). Reproduce
this rule exactly and your digests will match byte-for-byte.

### Recipient-identity normalisation (frozen)

Each sealed recipient identity — an email or a roster/centre label — is normalised by one
uniform rule before it enters the `assignments` list, so a third party reproduces the keyed
digest off-box from the key alone:

```
normalize(recipient) = lowercase( collapse_whitespace( strip( NFC(recipient) ) ) )
```

Unicode NFC → strip leading/trailing whitespace → collapse every internal run of whitespace to
a single space → lowercase. It is uniform on purpose: emails carry no internal whitespace and
are already lower/trimmed, so every real email identity is left byte-identical (join-campaign
digests are unchanged), while labels such as `"Centre  42 "` and `"centre 42"` normalise to the
same `"centre 42"`. **This rule is frozen for format `version` 1.**

The key header records how the mapping was made: `identity_scheme` (`"email"` | `"label"`) and
`roster_mode` (`"roster"` | `"count"` | `null`). Neither is needed to reproduce the digest
(the normalisation is uniform) — they tell an investigator how to read the identities.

## Commitments

**Codebook commitment** (`commitment.codebook_sha256`) — binds *which mark each copy carries*:

```
codebook_sha256 = SHA-256( canonical({
    "test_id": <campaign id>,
    "docs":    <the copies object: {doc_id: [page_meta,...]} for rendered text,
                or {doc_id: meta} for PDF carriers}>,
    # PDF carriers only — binds the exact distributed file bytes:
    "pdf_sha256": {doc_id: <sha256hex of that variant's PDF>}
}) )
```

`docs` is exactly the `payload.copies` object from the key (verbatim per-copy metas). For PDF
carriers, `pdf_sha256` values are the per-copy hashes carried in `payload.manifest.docs[]`
(the PDF bytes themselves do not travel). This digest is unchanged from the pre-v2 format, so a
key recomputes the same value a campaign was originally sealed with.

**Keyed commitment** (`commitment.keyed_sha256`) — extends the codebook to also bind *who
received which copy* and the seal kind:

```
keyed_sha256 = SHA-256( canonical({
    "commitment_version": 2,
    "test_id":            <campaign id>,
    "codebook_sha256":    <the value above>,
    "assignments":        <payload.assignments, verbatim>,
    "mapping_seal":        "snapshot" | "pre-distribution"
}) )
```

`assignments` is a list, **pre-sorted by `doc_id`**, of
`{"doc_id":..., "recipient":..., "assigned_utc":...}`. `recipient` is a **stable, portable
identity** — a normalised (trimmed, lower-cased) email — never a local database id, which
would differ between installations. Because `mapping_seal` is inside the hashed payload,
altering it changes the digest.

## Recovery-key envelope (`<campaign>.fdkey.json`, `format` version 1)

A JSON object. The header is cleartext (so conflict detection, the receipt, and third-party
digest checks work without decrypting); the sensitive core lives in `payload`.

```jsonc
{
  "format": "fingerprint-desk-recovery-key",
  "version": 1,
  "campaign_id":  "<test_id>",
  "campaign_label": "<human name>",
  "carrier_type": "rendered | pdf_preserved | pdf_raster | pdf_vector",
  "created_utc":  "<when the campaign was generated>",
  "exported_utc": "<when this key was exported>",
  "n_marked": <int>, "n_controls": <int>, "n_recipients": <int>,
  "commitment": {
    "codebook_sha256": "<64 hex>",
    "keyed_sha256":    "<64 hex>",
    "mapping_seal":    "snapshot | pre-distribution",
    "algo": "<human description>", "committed_utc": "<seal time>"
  },
  "encryption": null,               // reserved; a future build sets this when the
                                    // payload is encrypted at rest (Argon2id + AEAD)
  "payload_sha256": "<64 hex>",     // SHA-256(canonical(payload)) — truncation/tamper check
  "payload": {
    "test_id": "<test_id>",
    "manifest": { ... },            // the campaign manifest, verbatim (the codebook index)
    "copies":   { "<doc_id>": [<page_meta>, ...] | <meta> },   // per-copy ground truth
    "assignments": [ { "doc_id": "...", "recipient": "...", "assigned_utc": "..." }, ... ],
    "mapping_seal": "snapshot | pre-distribution"
  }
}
```

**Verifying a key** (what an independent tool does):
1. `SHA-256(canonical(payload))` must equal `payload_sha256`. Any mismatch ⇒ the file is
   truncated or altered; reject it (do not partially load).
2. Recompute `codebook_sha256` from `payload.copies` (+ `pdf_sha256` for PDF carriers) and
   `keyed_sha256` from that plus `payload.assignments` and `payload.mapping_seal`; both must
   equal the values in `commitment`.
3. Only then trust the mapping — and only as strongly as `mapping_seal` allows.

When `encryption` is non-null, `payload` is a base64 ciphertext and the header (including both
commitment digests) stays cleartext, so the digests remain checkable and escrowable without the
passphrase. The encryption parameters will be specified here when that build ships.

## Commitment receipt (`<campaign>-receipt.txt`)

A small, human-readable text file — fits in an email or one printed page — carrying the two
digests, the seal kind (prominently), the seal time, and the recomputation pointer above. It
contains **no ground truth**. Its purpose is escrow: deposit it with a third party (counsel, a
timestamping service, an append-only log) **before distributing copies**. A receipt held off
the issuing machine and dated before any leak is what turns "trust the operator's disk" into a
check anyone can perform. Even an operator who later loses everything still has the anchor
proving the codebook predated the leak.

## Versioning

`version` is an integer. A reader accepts any `version` ≤ the one it understands and refuses a
newer one with a clear message. Fields are only ever added, never repurposed, and every
constant needed to verify (or later decrypt) travels **in the file** — a key exported today
opens in a future build even if that build's defaults have changed. The canonicalisation rule
above is frozen for `version` 1 and will not change under it.
