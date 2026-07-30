# Smoke Test (spec v0.3, Section A)

Purpose: answer "is the physical channel hopeless or not" in 2 to 4 weeks of
solo work, as cheaply as possible. Single carrier (Brassil word-shift +
line-shift, the most downscale-robust), one page, NO Tardos, NO collusion.
This test must be able to FAIL cheaply, that is its purpose.

## Protocol
1. `python encode.py --out marked.png --meta meta.json` and print marked.png
   on a mono laser at 600 dpi, actual size, no "fit to page" scaling.
2. Photograph the print with one phone, flat (0 deg), good light, hand-held.
3. Send the photo through ONE WhatsApp hop (send to a second account,
   download the received file).
4. `python decode.py --img received.jpg --meta meta.json`
5. Read the GO/NO-GO line.

Also print and photograph the unmarked control (`encode.py --unmarked`) and
decode it against the marked meta: it must score near 0.5 (chance). If the
control scores high, the decoder is reading layout artifacts, not signal, and
every other number is meaningless.

## Go/no-go (on REAL captures only)
GO if word-shift raw bit accuracy >= 0.85 or line-shift >= 0.90.
NO-GO if the better carrier is under 0.60: the physical channel eats the
geometry and the design needs bigger shifts or a different carrier before any
further investment.

## Encoding details
300 dpi A4 render, 45 lines. Line-shift: triplets (control, marked, control),
marked baseline +/- 2 px (1/150 in), 15 bits/page. Word-shift: alternating
interior words only (adjacent coded words would share a gap and cancel, ISI),
gap +/- 3 px (1/100 in); the slot count follows the font's layout
(~273 bits/page with the bundled Liberation Serif, the default on every OS;
a different serif face gives a slightly different count). Payload 64 PRN bits with repetition,
majority vote. Decoder is blind (no fiducials, geometry from baselines and
profiles, sign decisions only, so scale-free); meta JSON is used only for
scoring.

## Synthetic sanity results (container-verified, NOT the real go/no-go)
Clean render -> decode: line 15/15, word 273/273, payload 64/64.
Synthetic WhatsApp (rot 0.4, persp, blur 1.0, 1600 px, q78): 100% / 100%.
Double hop (harsher first hop, then 1600 px q70): 100% / 100%.
Harsh 1200 px (rot 1.5, blur 1.8, q65): line 14/15, word 273/273.
Unmarked control through WhatsApp channel: line 0.47, word 0.54 (chance).

Caveat: the synthetic channel has no paper texture, printer PWM noise, sensor
noise, defocus nonuniformity, or page curl. Real numbers WILL be worse. The
synthetic pass only proves the decoder logic is sound before you spend paper.
