# Threat model

What this tool resists, and — more importantly — what defeats it. A forensic tool that
hides its limits is dangerous, because it invites false confidence in an accusation.

## Goal

Given a photograph of a leaked page from a document that was distributed as per-copy
fingerprinted copies, name the source copy **or** honestly decline, with a bounded
probability of falsely accusing an innocent copy.

## What it resists

- **Printing.** The mark lives in geometry that survives a laser/inkjet print.
- **Phone capture at an angle, ordinary light.** Deskew + sign-only differentials tolerate
  perspective and resolution changes.
- **Messaging recompression.** WhatsApp/Telegram resize + JPEG is part of the design target.
- **Cropping to a region** (partial): a full page is best, but the decode degrades to a
  *lead*, not silence, on a partial page — and stays honest (it declines rather than guesses
  when there is too little signal).
- **After-the-fact tampering with the codebook:** the SHA-256 commitment over *which mark
  each copy carries*, sealed at generation before distribution, makes that checkable by a
  third party. Tamper-evidence for the *who-received-which mapping* depends on the seal kind —
  see **Commitment seals** below; do not assume the mapping is provably pre-leak unless it was
  sealed `pre-distribution`.

## What defeats it (be explicit about this)

- **Retyping or AI transcription.** A leaker who retypes the questions, or runs OCR / an LLM
  to reproduce the text, carries **no geometric mark**. This is the fundamental limit of any
  layout-based scheme. It is the most likely real-world evasion.
- **Leaks before differentiation.** If the master leaks before per-copy copies are generated
  and distributed, there is nothing to trace.
- **Heavy re-rendering.** Re-flowing the document, screenshotting a reader that re-lays-out
  the text, or aggressive "enhance"/deskew edits that re-space lines can erase the signal.
- **Tiny fragments.** A single cropped question can point at a source but cannot, on its own,
  meet the evidence + margin gates or untangle a colluding group.

## Collusion

The current public pipeline is **single-carrier, no anti-collusion coding** (no Tardos
codes yet). Several colluders can average or splice their copies to weaken or confuse the
mark. Fragments from a group are leads for investigation, not proof of a specific individual.
Collusion-resistant coding is future work; see the spec.

## False accusation — the failure we refuse

The design treats a **false accusation as the worst outcome**, worse than a missed
attribution. The three-gate rule (corrected p ≤ 1e-3, minimum symbols, margin over
runner-up) and the mandatory unmarked **control** exist for this. Every operator should run
the control through the same pipeline; if the control is ever attributed, the result must
not be relied on and it is a release-blocking bug. Report such cases via
[SECURITY.md](../SECURITY.md).

## Commitment seals — what each actually proves

An accusation rests on two separate claims, sealed separately. Be precise about which you
hold, because they do not prove the same thing:

- **Codebook commitment** — *which invisible mark each copy carries*. Sealed at generation,
  **before any copy is distributed**, so it provably predates any leak. This is what makes the
  physical-mark side of an accusation checkable.
- **Mapping seal** — *who received which copy*. It carries one of two kinds:
  - `pre-distribution` — the mapping was fixed and bound before distribution, so it provably
    predates the leak.
  - `snapshot` — the mapping **as it stood when the recovery key/receipt was made**. It proves
    who held which copy at that time; it does **not** prove the mapping predates distribution,
    and an adversary can argue the mapping was altered after the fact.

  A `snapshot` is all a campaign can carry today: copies are assigned on join
  (first-come-first-served), so there is no pre-distribution roster to bind. Treat a snapshot
  mapping as corroborating, not as proof that the recipient link predates the leak. The seal
  kind is bound into the digest and printed on the recovery key and receipt; the exact format
  is in [recovery-key-format.md](recovery-key-format.md).

## Operator trust boundary

Ground truth (per-copy seeds, mappings, pack sheet→role tables) is what makes tracing
possible. Anyone holding it can trace; anyone who loses it can never trace **unless they
exported a recovery key first** (below). The app does not serve it to contributors over the
web UI, and volunteer-pack ground truth is private by design.

Two deliberate exports move a scoped slice of ground truth off the box, and change the story
above in your favour if used well:

- The **commitment receipt** carries only the digests and the seal kind — no ground truth.
  Deposit it with a third party *before* distributing copies; a receipt dated before any leak
  is what makes an accusation checkable without trusting the operator's disk.
- The **recovery key** carries the full codebook and mapping (but never the document). It is
  the backup that survives a lost data directory, and lets an investigation run on another
  machine. Because it *is* ground truth, whoever holds it can trace — so it is exported under
  a confidentiality warning and (in a later build) encrypted at rest. A leaked key exposes the
  who-received-which mapping, but never the document itself.

Protect and back up the data directory (the `/data` volume). A recovery key is the second line
of defence when that fails; the receipt is the anchor that survives even losing both.
