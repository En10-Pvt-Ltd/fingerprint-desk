# How This System Compares to Other Print-Marking Technologies

*(Analysis document. Claims about this system trace back to the repo record:
`spec-v0.3-delta.md` for the adversary model, carrier choice, and evidence
tiers; `PROGRESS.md` for the field-test numbers; `docs/story-for-everyone.md`
for the plain-language framing.)*

Three established technologies hide information in printed pages:

- **Steganographic halftoning** hides data in the dot patterns used to print
  grayscale images and shaded regions. It looks like ordinary solid ink or
  standard grey shading; the variations are microscopic.
- **Micro-typographic adjustment** shifts text geometry (lines, words,
  characters) by sub-millimeter amounts. It appears as normal text spacing.
- **The yellow dot matrix** (Machine Identification Code, MIC) is a grid of
  sub-0.1 mm yellow dots that color laser printers add to every page,
  encoding the printer's serial number and a timestamp.

All three are invisible to a human reader, and all three are conventionally
detected with high-resolution scanners or blue-light illumination. This
system belongs to the micro-typography family (the Brassil line-shift /
word-shift lineage), but it differs from all three — including generic
micro-typography as commercially deployed — in what it identifies, what
channel it survives, what guarantees it gives, and what it costs.

## Side-by-side

| | Yellow dot matrix (MIC) | Steganographic halftoning | Generic micro-typography | **This system** |
|---|---|---|---|---|
| What it identifies | The **printer** (serial + timestamp) | Authenticity of **image content** | The recipient's copy | The **recipient's copy** (traitor tracing) |
| Who controls the payload | Printer vendor firmware | Document producer | Document producer | Document producer (per-copy codeword) |
| Carrier spatial frequency | High (sub-0.1 mm dots) | High (halftone microstructure) | Low–medium | **Lowest available** (whole-line / whole-word positions, 170–250 µm shifts) |
| Needs to embed | Color laser printer with vendor MIC firmware | Halftone-controlled print pipeline; image/shaded content on the page | Software | **Software only; any mono laser** |
| Needs to detect | High-res scan or blue light, physical page or near-lossless capture | High-res scan, often registration to a reference | Usually scanner-quality recapture | **The leaked phone photo itself**; blind decode, no original, no fiducials |
| Survives phone photo + WhatsApp hop | No (dots vanish under downscale + JPEG) | No (microstructure destroyed) | Not designed for it | **Yes — field-validated** (M3 gate: 0.902 accuracy, controls at chance) |
| Removability | Separable from content: `deda` toolkit strips dots; mono printing never adds them | Reprint/re-screen destroys it (and the mark) | Re-typesetting | Re-typesetting only — which **destroys the leak's authenticity** |
| Collusion model | None | None | Typically none | **Tardos floor + position-blind region-routing analysis (Stage-0 purity decoding)** |
| Error guarantees | Heuristic ("this printer") | Heuristic | Usually heuristic | **Quantified false-accusation probability with tiers** (courtroom = 10⁻⁶), FPR-must-be-zero rule on unmarked controls |

## The four differences that matter

**1. It answers the forensic question a leak actually poses.** Yellow dots
tell you which *machine* printed a page — famously used in the 2017 Reality
Winner case — but when 5,000 recipients each hold a copy printed by the same
press, machine identity says nothing about *whose copy* was photographed.
Halftone stego verifies that image content is genuine; exam papers are
almost pure text. This system embeds a distinct codeword into each copy's
text geometry, so a photograph of the leaked page answers: *this came from
copy N.*

**2. It is engineered for the channel leaks actually use.** The listed
techniques are detectable only with lab equipment precisely because they are
high-spatial-frequency marks — and high frequencies are exactly what a
hand-held phone photo followed by WhatsApp's downscale (~1600 px, roughly
137 dpi effective) and JPEG recompression destroys. This system deliberately
uses the lowest-frequency carrier available: whole-line and whole-word
position shifts of 170–250 µm (two to three hair widths), read as
**sign-only differentials** (baseline-spacing for lines, adjacent-gap-width
for words), which makes the decoder scale-free across capture resolutions.
This is field-validated, not theoretical: the M3 physical gate in
`PROGRESS.md` records real print → hand-held phone photo → real WhatsApp
hop decoding at 37/41 = 0.902, with unmarked controls reading chance
(0.537) — the decoder reads embedded signal, not layout artifacts.

**3. It survives colluders and produces defensible numbers.** If two leakers
combine their copies, none of the three listed technologies has anything to
say. Here, the symbol layer carries a Tardos code (the unconditional floor
against the full marking adversary), and the realizable print colluder is
strictly weaker: photographing pages, they can only route whole regions from
one copy or another, so each leaked region purely convicts the copy it came
from (spec §1, Stage-0 purity decoding). The output is not "probably this
copy" but a false-accusation probability computed from the power-corrected
master inequality (`metrics.py`), mapped to evidence tiers — with the
courtroom tier at ε₁ = 10⁻⁶ and a hard rule that false positives on
unmarked controls must be exactly zero.

**4. Removing it costs the leaker the thing they want.** Yellow dots are
*separable* from the document: the TU Dresden `deda` toolkit strips them,
and a monochrome printer never adds them. This system's mark *is* the text
layout. Erasing it requires re-typesetting or OCR-and-retype of the whole
paper — slow, error-prone, and fatal to the leak's evidentiary value,
because what makes a leaked exam photo credible is that it is a photograph
of the *actual printed paper*, produced quickly on exam morning.

## Better at the lowest possible cost

The cost structure is inverted relative to all three alternatives, on both
ends of the pipeline:

- **Embedding: ~zero marginal cost.** Pure software at render time
  (`encode.py`; Stage 2's formatting-preserving PDF mode tags any uploaded
  PDF pixel-identically except for the nudges themselves). Prints on any
  commodity mono laser — no color printer, no special ink, no vendor
  firmware, no halftone-capable press. Serializing a print run is a
  per-copy PDF render.
- **Detection: the adversary pays for the capture.** MIC and halftone
  detection need a forensic scanner or blue-light rig *plus access to the
  physical page*. Here the evidence input is the leaked photo itself — the
  phone-and-WhatsApp chain the leaker already used delivers a decodable
  signal to a Python pipeline on a laptop.
- **Validation discipline as a cost strategy.** The build was staged so the
  cheap experiment could kill the idea before any expensive investment: a
  single-carrier smoke test whose only job was the physical-channel
  go/no-go. It passed on real captures, so the corpus harness investment is
  justified — in that order, never the reverse.
- **Staying cheap from here:** remain on Carrier 1 (no GPU/PyTorch until
  capacity demands it), sign-only decisions (no per-device calibration),
  repetition plus majority vote (no heavy ECC machinery), and the practical
  guidance already logged — prefer 11 pt+ serif body text — rather than
  raising shift amplitudes and paying a visibility cost.

## Real-world applications, contrasted

- **Yellow dot matrix** → law enforcement tracing a *physical printer*:
  counterfeit currency and documents, tracing printed leaks back to an
  office machine. Passive and ubiquitous, but machine-level only, defeated
  by mono printing, and requiring the page or a near-lossless scan.
- **Steganographic halftoning** → anti-counterfeiting and authentication of
  image-bearing items: packaging, tickets, secure IDs, currency artwork.
  Verifies genuineness under controlled scanning; does not trace recipients.
- **Commercial micro-typography** → per-recipient serialization of
  distributed documents, usually assuming a scanner-quality recapture of
  the physical page.
- **This system** → leak *attribution* for high-stakes distributed text
  documents — exam papers (the NEET reference case), board packets, legal
  discovery, pre-release scripts — where the realistic leak is a phone
  photo relayed through a messaging app, possibly by colluding insiders,
  and where the output must be a statistically defensible accusation, not
  merely a lead.

## Honest limitations

Consistent with the repo's disclosure discipline:

- **Capacity is small**: ~15 line bits and ~273 word bits per page raw,
  fewer after repetition coding. This is a fingerprint channel, not a data
  channel.
- **Text pages only**: the carriers live in line baselines and word gaps;
  image-only pages carry nothing (Carrier 2 would address this and is not
  yet implemented here).
- **Physical floor on type size**: field results favor 11 pt+ body text;
  small-print layouts degrade.
- **Re-typesetting defeats it** — at the authenticity cost described above.
- **Scale claims are mathematical so far**: the field test covered two
  tagged copies from one printer and one phone. The promise that guarantees
  hold at thousands of copies rests on the tier table, which the corpus
  benchmark campaign is designed to confirm.
