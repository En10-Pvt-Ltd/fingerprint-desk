# robust_decode: real-capture pipeline for Carrier 1

The shipped `decode.py` aborts on real print-photo-WhatsApp captures with
`LINE COUNT MISMATCH` (its fixed `0.10*max` row-profile threshold cannot cut the
raised inter-line valley floor that blur plus tight line spacing produces, and it
has no page crop or illumination correction). This folder is the preprocessing +
segmentation pipeline that gets a real capture through to a score. `decode.py` is
NOT modified; these scripts reuse its `deskew`, `line_baseline`, `subpixel_gaps`.

## The only real-world result to date

Produced by this pipeline on `received.jpeg` (marked.png, one WhatsApp hop):

```
line-shift : 14/15 = 0.933 raw bit accuracy
word-shift : 0/0   (355 erasures)   # gaps below resolution at full-page framing
```

Reproduce from repo root:

```
python robust_decode/run_robust.py --img received.jpeg --meta meta.json
```

This is a GO on the line-shift carrier (>=0.90), and it is now VALIDATED by the
unmarked control (see below).

## Control result (validates the 0.933)

The unmarked control (`control_received.jpeg`, matched framing, one WhatsApp hop)
through this same pipeline against the MARKED `meta.json`:

```
line-shift : 4/13 = 0.308 raw bit accuracy   # chance; 1.4 sigma below 0.5 at n=13
word-shift : 6/9  = 0.667 (346 erasures)     # n=9, also consistent with chance
```

The control scores at chance on line-shift, far from the marked 0.933 (marked
14/15 has P ~ 4.9e-4 against a fair coin; control 4/13 is within ~1.4 sigma of
chance). The pipeline is reading embedded line-shift signal, not layout geometry.
Caveat: the control is a single capture with only 13 line bits and 9 word bits
scored, so the validation is directionally decisive but statistically thin.

## Files

- `run_robust.py` — parameterized single-command pipeline (crop -> flat-field ->
  deskew -> autocorrelation line segmentation -> decode.py scoring). Use this.
- `crop_page.py`, `flatfield.py`, `decode_robust.py` — the original scratchpad
  scripts, committed verbatim to preserve the exact artifact that produced 0.933.
  `decode_robust.py` hardcodes `received_cropped.jpg` / `meta.json`;
  `flatfield.py` was a diagnostic (its flat-field is inlined in the others).

## Pipeline steps

1. Crop to the paper: Otsu largest-bright-component bbox, 3% inset. Removes the
   dark table surround that otherwise floods every row's ink profile.
2. Flat-field: 25x25 grayscale morphological close estimates the illumination
   field; divide to restore the gray paper cast (~median 181) to white (~245),
   keeping antialiased text edges for sub-pixel gap reads.
3. Deskew (decode.py) then segment lines by BLIND autocorrelation pitch (search
   30..120 px) + peak detection with 0.6*pitch min separation, band boundaries
   at peak midpoints. Recovers all 45 lines where the global threshold found 1.
4. Score with decode.py's `line_baseline` and `subpixel_gaps`, sign decisions
   only. Line-shift second-difference within triplets largely cancels the smooth
   perspective spacing gradient (peak spacings ran 21 px top to 34 px bottom).

## The control run (DONE, passed)

Reproduce:

```
python robust_decode/run_robust.py --img control_received.jpeg --meta meta.json
```

Line-shift lands at chance (0.308 at n=13), decisively below the marked 0.933,
so the pipeline reads embedded signal, not layout. See "Control result" above.

Earlier, a synthetic-channel control (`control_captured.jpg` from channel.py)
scored line 0.467 / word 0.499; that was a sanity check, not a real photo. The
real control above supersedes it.
