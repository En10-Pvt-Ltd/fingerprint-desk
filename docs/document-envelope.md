# Document envelope — tested evidence

This records **what was actually tested** behind the "What documents work" guidance in the
README and the vertical claims on the demo site, so the next person who asks "does this work
for board papers?" gets the measured answer instead of repeating the experiment. The
[generate-time self-verify guard](method.md#self-verify-at-creation) remains the per-document
guarantee; this page is the evidence for the *guidance*.

**How these were tested** (2026-07-31, app at the guard build, selftest 299): one
representative document per claimed vertical, run through the full pipeline — upload →
`analyze-pdf` → create → generation → the self-verify guard (each copy's own clean render
decoded through the real investigation decoder; pass iff the true copy self-attributes with
agreement ≥ 0.95). "PASS" means the campaign generated; "FAIL" means the guard refused it,
with the recorded cause.

## Verticals

| Vertical | Representative document tested | Outcome | Notes |
|---|---|---|---|
| Legal discovery | 8 pages of continuous legal prose | **PASS** | Dense produced documents are squarely in the envelope. |
| Manuscripts / screeners | 12 pages of continuous prose | **PASS** | Long continuous prose is the best case. |
| Board papers | 6 pages: 5 prose + 1 financial-table page | **CONDITIONAL** | Passed **because** the pack was prose-heavy — it self-attributed off the prose pages. A pack dominated by financial tables, charts, or slides carries too few readable text lines and fails. Claim requalified to **prose board minutes and briefs**, explicitly not financial packs or slide decks. |
| Internal memos | 1-page memo | **FAIL** (`too_little_content`) | A typical memo is too short to carry the minimum 10 readable marks. Only a multi-page prose memo would pass, which is not what most people mean by "memo" — **dropped as a headline vertical**. |

## Flagship case (long plain-text report)

A 30-page single-column plain-text report, end to end: `analyze` accepted → guard **passed**
(generation 18 s) → bulk **ZIP download** delivered 4 recipient-named copies plus the isolated
`_control/CONTROL-unmarked-do-not-distribute.pdf`, `README.txt`, and `copies.csv`, archive
integrity verified.

## Everyday-document sample (why the envelope is stated up front)

A sample of 14 real, everyday PDFs from one machine (passports, tax forms, invoices, bank
statements, an ECG report, CVs, a wedding invitation, a brochure, scans):

- 3 were refused at upload (password-protected; scanned image with no text layer).
- Of the rest, **none produced a traceable campaign**: forms/statements/invoices carried 0–6
  markable lines (guard cause `too_little_content`); CVs, invitations, and brochures embedded
  marks that read back at chance (~0.6) because columns/graphics defeat the geometric decoder
  (guard cause `unreadable`).

That result is what prompted stating the envelope at the top of the README rather than
letting operators discover it at generation: **most everyday PDFs are outside the envelope by
the physics of line-shifting.** The method needs long, continuous, plain body text.

## Reproducing

Upload any document and generate a campaign; the guard's verdict and per-variant self-decode
numbers are recorded in the campaign manifest under `self_verify` (cause `unreadable` vs
`too_little_content`). A refused campaign is recorded with status `rejected` and the
plain-language reason shown in the UI.
