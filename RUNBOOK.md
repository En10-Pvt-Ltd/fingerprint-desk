# Phase B Corpus Runbook

End-to-end commands from printing through bakeoff, plus the capture matrix as a
checklist. The physical channel already passed Phase A (marked line-shift 0.933,
control at chance). This is the make-or-break benchmark.

## Hard rules (do not violate)

- Score real captures ONLY through the robust pipeline (`robust_decode/`), never
  `decode.py`. `decode.py` is full-page-synthetic only and aborts on real
  captures with LINE COUNT MISMATCH. The harness already wires c1 to
  `robust_decode/c1_decoder.py`; do not repoint it.
- Nothing produced by `channel.py` (the synthetic simulator) may enter the
  corpus. `apply_channels.py` refuses a synthetic parent, and `run_bakeoff.py`
  skips any sidecar with `synthetic: true`. Use `channel.py` for sanity only.
- Printer and stock are recorded at capture time, not baked into the PNG. One
  document PNG is printed on every (printer, stock) you have.
- Frozen splits: variants 1-3 tuning, 4-5 + all controls report. No physical
  page is shared across splits. Do not retune on report pages.

## Setup

```
pip install -r requirements.txt
```

## Step 0. Generate the document set (once)

```
python gen_corpus_docs.py --corpus corpus
```

Produces `corpus/docs/v1..v5` (marked, distinct codewords), `ctrl1..ctrl5`
(unmarked controls), each with ground-truth meta, and `corpus/splits.json`. It
also registers `dry_marked` / `dry_control` from the existing Phase A captures;
DELETE those two docs and their captures before the real campaign (they are not
part of the 35).

## Step 1. Print

Print each `corpus/docs/<doc_id>.png` at **actual size / 100%**, never "fit to
page" (scaling destroys the sub-pixel geometry). Mono laser 600 dpi is the Phase
A-validated path. Print each doc on every (printer, stock) in
`corpus_config.json`. Write the `doc_id` on the REVERSE of each sheet only, never
on the captured face.

Spec target is 3 printers x 2 stocks x 5 variants + 5 controls = 35 physical
documents. The rig config currently lists fewer; extend `corpus_config.json`
`printers` / `stocks` as hardware arrives (the `*_spec_target` keys record the
goal).

## Step 2. Photograph and intake

Photograph hand-held, flat, naturally (no tripod): the corpus must look like a
leak, not a lab. Intake every photo immediately so it never exists without
metadata:

```
python intake.py --img <photo.jpg> --doc_id v4 \
    --printer laser_mono_600 --stock plain_80gsm --phone flagship \
    --angle 15 --lighting office --framing full [--tag 2] [--screen-reshoot]
```

`intake.py` validates every field against `corpus_config.json`, copies the file
into `corpus/captures/` under a deterministic `capture_id`, and writes the
sidecar. Re-shots of an identical condition need a distinct `--tag`.

## Step 3. Messaging multipliers

Fan each real capture into the messaging chains (applied to real photos only):

```
for f in corpus/captures/*.jpg; do
  python apply_channels.py --in "$f" --outdir corpus/derived --chains all
done
```

AI-cleanup passes (Real-ESRGAN, SD img2img, CamScanner) stay external on the GPU
box; `apply_channels.py` prints the exact commands. Run them on the messaging
outputs and re-intake results with `--cleanup` recorded (extend intake if you
wire cleanup in-loop).

## Step 4. Bakeoff

```
python run_bakeoff.py --corpus corpus --out bakeoff.csv --summary bakeoff_summary.md
```

Emits per-capture `bakeoff.csv` (both scorings: soft via k_eff, hard-proven via
flip, at beta 0.5 and 0.9, n=5000, budget 5e-7) and `bakeoff_summary.md`
(per decoder x framing trace-success + control FPR). Exit code is non-zero and
the failure is printed loudly if any unmarked control crosses the courtroom
threshold against any codeword.

## Step 5. Read the result

- Pivot `bakeoff.csv` on (framing, messaging, cleanup) for the heatmaps.
- Compare c1 vs fused; c2 is a stub until the learned decoder trains.
- The prediction to falsify: c1 wins clean high-dpi cells, c2 wins cleanup and
  low-dpi cells, fusion dominates everywhere. If fusion does not dominate once
  c2 lands, the LLR calibration is broken; fix that before concluding anything.
- FPR gate must stay at zero courtroom accusations. One false accusation fails
  the build.

Note on scale: with the current 64-bit smoke payload each full-page capture
yields only ~15 observed line symbols (k_eff ~8), so tiers read "no guarantee"
even at 0.933 accuracy. That is arithmetic, not failure. The real campaign uses
the full Tardos payload (target k in the thousands per full paper), which is
where the courtroom tier becomes reachable. The harness, scoring, and gates are
correct at any k.

## Capture matrix checklist

Per spec v0.3 Section 3.2, sampled (not full factorial). Dimensions:

| dimension | values | count |
|---|---|---|
| phone | budget, mid, flagship | 3 |
| angle (deg) | 0, 15, 30, 45 | 4 |
| lighting | office, dim_tube, flash_glare, window_backlight | 4 |
| framing | full, half, single-question, single-paragraph | 4 |

Full factorial is 3 x 4 x 4 x 4 = 192 cells per document. Do NOT shoot all of
them. Curate ~40 cells that span the space, ~30 shots each, hand-held:

- Target ~1,200 real captures total (2-3 person-days with a shot-list app that
  stamps metadata).
- Each real capture x 5 messaging chains x 5 cleanup passes = up to ~30,000
  scored images.
- Always include the unmarked controls at matched framing/tilt to their marked
  siblings. Controls are the FPR gate; skipping them invalidates every number.

Per-condition checklist (tick per document, per printer x stock):

- [ ] full framing, 0 deg, office, all 3 phones
- [ ] full framing, 15/30/45 deg, office, flagship
- [ ] full framing, 0 deg, each of dim_tube / flash_glare / window_backlight
- [ ] half framing, 0/15 deg, office + one harsh light
- [ ] single-question framing, 0 deg, office + flash_glare (word-shift needs the
      higher effective dpi of a crop; full-page WhatsApp erases it)
- [ ] single-paragraph framing, 0 deg, office
- [ ] screen-reshoot probe: 2-3 cells with `--screen-reshoot`
- [ ] every control doc: full + one fragment framing, matched to its marked twin

Word-shift reminder: Phase A showed word-shift fully erased on a full-page
WhatsApp send (gaps below the resolution floor). Expect word-shift to score only
in crop / single-question / single-paragraph framings. Line-shift is the
downscale-robust carrier and should carry the full-page cells.
