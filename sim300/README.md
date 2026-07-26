# sim300 — 300-contributor stress-test simulation

Answers: *if N contributors each print a different fingerprinted variant of
the same document and photograph it at various angles/qualities, how many
does the system identify correctly, and does it ever accuse the wrong
variant?*

No custom decoder: scoring calls `engine.scan_pdf.attribute` (pdf_preserved
tests) or `engine.scan.attribute` (text tests) — the exact functions behind
the app's `POST /api/tests/{id}/scan` upload route.

## Phases

```bash
# smoke pass (12 variants + 3 controls, all four phases)
python sim300/run_sim.py --limit 12

# full run
python sim300/run_sim.py
```

Individual phases: `--build`, `--simulate`, `--score`, `--report`
(default: all four in order). Other flags: `--n` (variants, default 300),
`--pdf <path>` (source PDF; default `docs/Niraj_Kasar_Resume_2025 (1).pdf`),
`--text` (rendered text-mode corpus, `SAMPLE_TEXT` extended to 4+ pages),
`--text-file <path>` (rendered text-mode corpus built from a file's content
instead of `SAMPLE_TEXT`; corpus name is derived from the filename, e.g.
`docs/neet-2018-physics-section.txt` -> `sim<N>-neet-2018-physics-section`),
`--workers`, `--keep-work`.

- **build** — one test with N marked variants + 3 unmarked controls via the
  engine's own generation (`render_pdf.generate_pdf_test` /
  `render.generate_test`) under `FF_APPDATA=sim300/out/appdata`. Idempotent.
- **simulate** — every page PNG is degraded deterministically (seeded by the
  variant index, no wall-clock randomness): perspective keystone for a
  camera tilted 0/15/30/45° about the horizontal axis (real projective
  geometry, top edge compressed), in-plane jitter ±2°, blur σ0.6, noise
  σ2/255, then a messaging chain — wa (1600 q78), wa2x (that twice),
  harsh (1200 q60), brutal (1000 q45). 16 cells; controls get wa at
  0/15/30°. Captures land in `sim300/out/captures/`.
- **score** — multiprocess scan of every capture against the full manifest;
  writes `rows.csv` (full treatment recipe + verdict per capture) and
  `percand.jsonl` (per-candidate ok/tot for pooling).
- **report** — `sim300/out/summary.md` (16-cell tables: per-photo
  identification, argmax accuracy, abstention; per-contributor pooled
  attribution; wrong-accusation counts; control results; measured-capacity
  collision math; breaking-point narrative) and `sim300/out/report.html`
  (per-capture inspector: degraded image thumbnail, exact treatment,
  outcome, with client-side filters).

Environment: `FF_FONT_PATH` defaults to `C:\Windows\Fonts\times.ttf`,
`FF_APPDATA` to `sim300/out/appdata`. Everything under `sim300/out/` is
gitignored.
