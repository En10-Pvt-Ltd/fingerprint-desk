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
- **After-the-fact tampering with the mapping:** the sealed SHA-256 commitment makes an
  accusation checkable by a third party.

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

## Operator trust boundary

Ground truth (per-copy seeds, mappings, pack sheet→role tables) is what makes tracing
possible. Anyone holding it can trace; anyone who loses it can never trace. The app keeps it
server-side in the data directory and never serves it; volunteer-pack ground truth is
private by design. Protect and back up that data directory (the `/data` volume) accordingly.
