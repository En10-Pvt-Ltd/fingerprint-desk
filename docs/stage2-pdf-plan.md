# Stage 2 plan: formatting-preserving fingerprinting of foreign PDFs

Status: ALL MILESTONES COMPLETE (M1, M2, M3, M4). Stage 2 is validated
end to end, including physically.

M3 result (2026-07-13, full record in appdata/m3/RESULT.txt): GATE PASSED
on doc01_times11 through a real print -> hand-held phone photo -> real
WhatsApp hop: true-variant aggregate 37/41 = 0.902 (page-1 captures 14/14
at p = 6.1e-5 and 13/14 at p = 9.2e-4), control aggregate 16/26 = 0.615
(chance band). Caveats recorded with the pass: the control evidence is
doc02's control only (capturing doc01's own control is the recommended
strengthening step), and doc02_helv_headings did not validate (one
segmentation near-miss, one chance-level read; the plan requires one
passing document class). The physical run also drove three pipeline
hardenings: a shadow-tolerant union page crop, a meta-guided line
segmenter for variable layouts, and foreign-document rejection with an
--identify mode in m3_check.py that resolved a real sheet mix-up in the
user's captures.

M4 result (2026-07-13): the app's wizard offers a "preserve original
formatting" mode when a PDF is imported (POST /api/analyze-pdf reports
markable line bits per page with the real-photo capacity warning);
generation emits the customer's own PDF with embedded line shifts per
variant plus byte-copy controls (engine/render_pdf.py); the sealed
codebook commitment binds the metas AND the emitted PDF hashes; scans
dispatch to the Stage 2 decoder (engine/scan_pdf.py) with the same
Bonferroni/binomial attribution rule. app/selftest.py extended to 38
checks, all passing: WhatsApp leak of a preserved variant attributes at
14/14 (p_adj 1.2e-4), control at chance, control PDF byte-identical to
the source, fingerprinted PDF download streams the embedded file.

M3 kit (2026-07-13): app/tools/m3_kit.py emits print-ready v1/v2/control
PDFs + metas for doc01_times11 (Times, 2 pages, 28 slots) and
doc02_helv_headings (Helvetica + headings, 14 slots), seeds 7001/7002.
app/m3_check.py scores captures dropped into appdata/m3/captures/ via the
robust photo pipeline (crop, flat-field, deskew, threshold/autocorr
segmenter ladder in pdf_scan.observe_page_robust) and evaluates the gate
(>= 0.90 on a document AND control at chance). Its --selftest round-trips
the kit's own PDFs through synthetic WhatsApp captures: both docs 14/14
via robust+threshold. Stage 1 (PDF as content source, text
re-flowed through the app's own layout engine) shipped in
app/engine/pdf_source.py.

M1 result (2026-07-13): app/engine/pdf_mark.py (band analysis + content-
stream line-shift with compensation), app/tools/m1_corpus.py (10 varied
documents incl. Td-chain and TL/T*/quote streams, tight leading,
justified, lists, headings, superscripts), app/m1_check.py (round-trip
checker). 240 marked-line embeddings across 10 docs x 2 seeds: every
marked baseline moved exactly +/-2 px at 300 dpi (worst error 0.000 px),
every other line 0.000 px, zero pixel change outside marked-line rows.
Two checker-side measurement pitfalls found and fixed (band-padding in the
reused research baseline finder; descender rows detaching into separate
ink runs). The embedding itself needed no correction after the round trip.

M2 result (2026-07-13): app/engine/pdf_scan.py (meta-guided blind decode:
deskew + line segmentation from the image, band triplets located by the
meta's page line order) + app/m2_check.py harness. Nine markable documents
x 3 variants x pages through channel.py presets: clean and WhatsApp decode
at 100.0% true-variant line-bit accuracy (378/378 aggregate at WhatsApp),
wrong variants and controls at chance (controls 0.513-0.520 across 900
scorings). Measured findings folded back into the engine:
  - PITCH FLOOR: 10.08 pt pitch (9 pt / 1.12 leading) loses segmentation
    lines already at the WhatsApp preset; 14.17 pt passes everything.
    pdf_mark.MIN_PITCH_MARK = 12.0 now excludes sub-floor bands from
    marking (recorded in meta as excluded_bands); refine at M3.
  - HARSH preset is reported as ungated stress data (0.70-1.00 by
    document; one heading/body merge case), consistent with the research
    baseline where harsh costs the native encoder a line bit (14/15).
    The product reference channel remains WhatsApp-grade.

## Objective

Take a customer's existing text PDF, emit n visually identical fingerprinted
PDF copies plus ground-truth metas, such that a phone photograph of a printed
copy attributes through the existing scan flow. The original layout, fonts
and pagination are preserved exactly; only invisible geometry moves.

## Scope

IN: born-digital, single-column, predominantly regular body text (exam
papers, prose board minutes and briefs — not financial packs or slide
decks, which carry too few text lines). Line-shift carrier only. A4/Letter.
OUT (explicitly): scanned/image-only PDFs (no text objects to move),
word-shift on justified text, multi-column layouts, fragment decoding.
Word-shift via TJ-array spacing and multi-column support are Stage 3
candidates, gated on Stage 2's measured margins.

## Why line-shift only

The current blind word-shift convention reads the sign of adjacent-gap
differentials and is only sound because the encoder renders uniform nominal
gaps. Foreign PDFs (especially justified text) have naturally unequal gaps,
so word-shift needs reference-assisted decoding plus registration, a bigger
lift for the weaker carrier (word bits die on full-page phone photos
anyway; Phase A measured this). Line-shift needs only locally uniform
baseline pitch, which regular paragraphs give us for free, and it is the
carrier that survived the real print-photo-WhatsApp test at 0.933.

## Architecture

1. **Layout analysis** (PyMuPDF): extract per-page text blocks with
   baselines. Select "markable bands": runs of >= 3 consecutive body-text
   lines with near-uniform pitch (tolerance ~5%), skipping headings,
   lists with large leading, table zones, and lines whose neighbors sit in
   different blocks. Group into triplets (control, marked, control), same
   public convention as encode.py.
2. **Embedding** (pikepdf or PyMuPDF content-stream edit): for each marked
   line, translate its text-showing operations vertically by
   +/- LINE_SHIFT_PT = 0.48 pt (the 2 px at 300 dpi used today). Everything
   else in the content stream is untouched, so rendering is byte-stable
   outside the marked lines. Emit one PDF per variant plus unmarked
   controls printed from the same pipeline.
3. **Ground truth meta v2**: per page, the selected bands, each line's
   original baseline y, pitch, triplet position and bit. Schema extends the
   existing meta (decoder keeps driving everything from meta).
4. **Decoding**: reuse the robust capture pipeline (crop, flat-field,
   deskew, autocorrelation line segmentation) but score triplets only
   inside markable bands, mapped by the band's line count and relative
   position; leftover lines (headings etc.) are ignored rather than
   assumed. The baseline second-difference statistic is unchanged and
   stays scale-free. This is still blind at capture time (no registration
   against the original render needed for line-shift).
5. **App integration**: wizard gains a "preserve original formatting"
   toggle when the content came from a PDF; capacity preview reports
   markable line bits per page (with the same real-photo warning); the
   scan flow is unchanged.

## Milestones and acceptance criteria

- **M1 Embedding round-trip (digital):** fingerprint a corpus of ~10 varied
  real-world text PDFs; rasterize at 300 dpi; a meta-driven checker
  measures every marked baseline moved by the target amount and every
  unmarked line unmoved (tolerance 0.3 px). Visual diff shows no reflow.
- **M2 Synthetic channel:** rasterized variants through channel.py presets
  decode with line-bit accuracy >= 0.95 on markable bands; unmarked
  controls read at chance (0.4-0.6). Same honesty gates as today.
- **M3 Physical revalidation (required, not optional):** print 2 variants +
  1 control of 2 documents, photograph, one WhatsApp hop, scan through the
  app. GO gate: line accuracy >= 0.90 on at least one document class, real
  control at chance. The Phase A validation used our renderer's font and
  pitch; foreign fonts/pitches change the operating point, so this must be
  re-measured, not assumed.
- **M4 App wiring + selftest:** end-to-end selftest extends app/selftest.py
  with an M1-corpus document (create from PDF with formatting preserved,
  simulate WhatsApp leak, attribute; control at chance).

## Risks and mitigations

- **Tight leading or small pitch** makes +/-0.48 pt invisible to the
  decoder or visible to the eye: M1 measures per-document pitch and the
  wizard refuses documents whose median pitch is below a floor (surfaced
  honestly, like the current line-bits warning).
- **Content-stream edge cases** (Type 3 fonts, inline images interleaved
  with text, rotated text): layout analysis excludes such lines from
  markable bands; worst case a page carries fewer bits, which the capacity
  preview already reports.
- **Segmentation on sparse pages**: pages with little body text fall below
  the attribution threshold; same warning machinery as Stage 1.
- **Tamper surface**: fingerprinted PDFs are distributed digitally before
  printing; the sealed-codebook commitment must cover the emitted PDFs
  (hash each variant PDF into the manifest alongside the metas).

## Estimate

Three to five focused working sessions: M1 ~1, M2 ~0.5, M3 ~1 plus print
and capture time, M4 ~0.5, slack for content-stream edge cases.
