# field-test-002: physical revalidation of formatting-preserving PDF fingerprinting

Real print, hand-held phone photo, one real WhatsApp hop, blind decode.
This pack is self-contained provenance for the Stage 2 M3 gate result:

**GATE PASSED on doc01_times11: true-variant aggregate 37/41 = 0.902;
its two page-1 captures read 14/14 (p = 6.1e-5) and 13/14 (p = 9.2e-4);
its own unmarked control reads 4/14 and 9/14 (chance). Control aggregate
across both document classes: 29/54 = 0.537.**

All marks are LINE-SHIFT bits (this carrier has no word-shift): selected
text baselines moved by 0.48 pt, embedded directly into the PDFs' content
streams so the documents render identically except for the nudges.

## Layout

- `print/` - the exact PDFs that were printed (marked v1/v2 + unmarked
  control per document), sha256-pinned in provenance.json.
- `metas/` - ground-truth metas (which line carries which bit).
- `captures/` - the original received-from-WhatsApp photo files, named by
  true sheet identity (see "sheet custody" below).
- `foreign/` - a photo the operator submitted by mistake: a different
  document entirely. Preserved because the decoder's rejection of it is
  part of the evidence.
- `decodes/` - one JSON per capture: pipeline path, deskew, line counts,
  per-variant line-bit scores and one-sided binomial p. Regenerate with
  `python field-test-002/make_decodes.py`.
- `pixel-diff/` - evidence for "nothing changes but the nudges" on a
  fancy-layout document (Helvetica + bold headings): gold-on-navy map of
  every changed pixel plus stats. 141,680 pixels differ (1.6%), and every
  one of them lies inside a marked line's own row span; zero changes
  elsewhere. Regenerate with `python field-test-002/pixel_diff.py`.
- `provenance.json` - commands, thresholds (with explicit set-before vs
  set-after disclosure), sheet-custody narrative, and sha256 fingerprints
  of every archived file and of the decoder code.

## Sheet custody (read this before citing the result)

Printed sheets are visually identical by design, and the operator's first
naming was wrong for doc01 (labels rotated, plus one photo of an unrelated
document). The mix-up was detected because a "control" capture correlated
13/14 with a variant codeword, which an unmarked sheet essentially cannot
do; `python app/m3_check.py --identify` then identified every photo by its
geometry alone, and the operator confirmed against the pencil labels on
the sheet backs before files were renamed. The unrelated photo is kept in
`foreign/`.

## Foreign-document rejection: how the decision was made

Two mechanisms, with different provenance status (full detail in
provenance.json):

1. **Attribution soundness (pre-set):** the accusation rule (one-sided
   binomial p, Bonferroni-corrected, threshold 1e-3, minimum 10 bits) was
   fixed before any capture existed. In the run where the foreign photo
   WAS segmented, it scored at chance against every variant and produced
   no attribution. The system never risked accusing anyone from it.
2. **Segmentation validity (partly post-hoc):** the guided segmenter's
   ink-quality floor (0.9) predated the foreign photo, but the scale-band
   and valley-contrast checks that reject it outright in the final
   `--identify` run were added AFTER observing it slip past quality alone.
   These are usability filters, not the accusation gate, and this pack
   says so rather than presenting the rejection as fully pre-registered.

## Scope

Two marked copies plus controls, one printer, one phone, one WhatsApp hop,
two document classes; the 10 pt heading-heavy class did NOT validate and
is recorded as such. National-scale guarantees rest on the analytic tier
table and the planned corpus campaign, not on this field test.

## Open item

`provenance.json > whatsapp_chain.topology` awaits the operator's
attestation: device-to-device or send-to-self.
