# Method

How Fingerprint Desk embeds a per-copy code in printed geometry and recovers it blind from
a phone photo. This is the practical summary; the academic framing is in
[`spec-v0.3-delta.md`](../spec-v0.3-delta.md).

## 1. The signal: sub-millimetre geometry

Every copy shows identical text but a different pattern of tiny spacing shifts, from the
Brassil family of layout codes:

- **Line-shift.** Lines are grouped in **triplets** `(control, marked, control)`. Only the
  middle line carries a bit: its baseline is nudged up or down by `LINE_SHIFT = 2 px` at
  300 dpi (1/150 in). The control lines above and below give the decoder a local reference,
  so the shift is read as a *differential*, not an absolute measurement. ~15 line bits/page.
- **Word-shift** (rendered carrier). Only odd interior word slots carry bits; a bit widens
  one gap and narrows the next by `WORD_SHIFT = 3 px` (1/100 in), a local redistribution
  that leaves neighbouring words in place. Adjacent coded slots are skipped so their shifts
  don't interfere. ~273 word bits/page.

Both are below the threshold of notice for a reader, and both survive print and a phone
photo because they are *relative* positions of features that the channel preserves.

## 2. The payload

A 64-bit pseudo-random codeword is derived from a per-copy seed and written across the
available slots with **repetition**, then recovered by majority vote. Different copies get
different seeds, hence different codewords.

## 3. Commitment: accusations you can check, not trust

Before any copy is distributed, a **SHA-256 commitment** is sealed over the codebook — every
copy's metadata and, for PDF carriers, the exact emitted file bytes. Because *which mark each
copy carries* is fixed and hashed up front, an accuser cannot quietly change it after a leak
appears: a third party recomputes the commitment and verifies it is the original codebook.

The separate question of *who received which copy* is bound by a second, keyed commitment
carried on the recovery key and receipt, and it comes in two strengths. A **roster** campaign
(a fixed list of recipients, or a count pattern) binds the mapping at creation and seals
`pre-distribution` — proof the mapping predates distribution. A **join** campaign (contributors
claim copies over time) can only seal `snapshot` — the mapping as it stood at export, which is
corroborating, not proof it predates the leak. Both seal kinds, and how to recompute either
digest, are specified in [recovery-key-format.md](recovery-key-format.md); the trade-off, and
the one unsealed link in a count-mode roster, are in
[threat-model.md](threat-model.md).

## 4. Decode: blind and scale-free

The decoder needs only the leaked image — no original, no fiducial marks:

1. **Deskew** by searching rotation angles for the sharpest row profile.
2. **Segment lines** from the row profile; find each baseline from the bottoms of connected
   components (rejecting descenders).
3. **Measure** baseline-spacing differentials (lines) and adjacent-gap differentials
   (words) with sub-pixel edge interpolation.
4. **Read only the sign** of each differential. Because the decision is sign-only, it is
   **scale-free**: it works across capture resolutions without knowing the original size,
   and there is no absolute-measurement path to miscalibrate.

For scanned and outline-text PDFs the observation is *meta-guided* — the known strip
pattern is fit to the capture and each strip's sub-pixel displacement is read the same way.

## 5. Attribute, or refuse to

Each candidate copy's observed bits are scored against its codeword and turned into an exact
binomial p-value against chance. A copy is accused **only** when all three gates pass:

- **Evidence:** Bonferroni-corrected p ≤ `1e-3` (corrected for the number of copies), and
- **Enough signal:** at least `MIN_BITS = 10` symbols observed, and
- **Separation:** the top copy beats the runner-up by `max(4 bits, 8% of observed bits)`.

Otherwise the verdict is an honest **no attribution**. That is a correct outcome — expected
for an unmarked control, a foreign document, or a capture too degraded to read — not a
failure. A control copy that ever clears the gates is a release-blocking bug.

Multiple photos from one contributor are **pooled** by taking the best-read photo of each
page (same-page photos are correlated, so they don't stack), which strengthens a reading
without inflating it.

### Self-verify at creation

The same rule runs once more, *before* any copy leaves the machine. When a campaign is
generated the app decodes **each copy's own clean render** through this exact decoder and
requires it to attribute to itself — top copy, accuracy ≥ `0.95`, clearing the gates above.
If the true copy does not win, the campaign is **refused** (fail closed, no override), and
the cause is named because the remedies differ:

- the marks **don't read back on this document type** (heavy headings, graphics, columns) →
  switch to a document that is mostly continuous body text; or
- there are **too few readable marks** to clear `MIN_BITS` even from a flawless render (the
  document is too short) → use a longer document, or more pages.

A document that could never trace a leak is rejected at creation, not discovered after a
print run. Round-trip readability is a property of the layout, shared across copies, so a
bounded sample of copies is checked.

## 6. Carriers

One rule and one meta schema, four ways to apply the shift:

| Carrier | Input | Where the shift goes |
|---|---|---|
| Rendered | text | app re-typesets; shifts lines + words |
| Preserved | text PDFs | edits text-showing ops in the content stream |
| Raster | scanned / image-only PDFs | nudges pixel-row strips of the page image |
| Vector | outline-text PDFs | translates each line's vector paths |

Scanned and vector documents keep everything outside a shifted line **pixel-identical** or
**byte-exact**, so tables, figures, stamps, and letterheads are preserved.

## 7. The guarantee chain

`metrics.py` turns observed accuracy into the forensic statement: symbol-error rate,
effective observed-symbol count, and a tier — courtroom / strong lead / weak lead / no
guarantee — from the power-corrected master inequality over `(copies, symbols, error rate,
population, β)`. The real constant comes from the benchmark corpus, not from simulation.
