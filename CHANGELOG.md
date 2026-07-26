# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-26

First tagged snapshot: the research pipeline plus the public application.

### Added
- **Forensic method.** Blind, scale-free geometric fingerprinting — line-shift (triplet
  convention, ±2 px @ 300 dpi) and word-shift (±3 px) — with a 64-bit PRN payload embedded
  by repetition. Decode reads only the sign of each differential.
- **Attribution rule with a false-accusation discipline.** Bonferroni-corrected exact
  binomial p ≤ 1e-3, minimum 10 observed symbols, and a margin over the runner-up
  (`max(4 bits, 8%)`); otherwise an honest no-attribution. SHA-256 commitment sealed over
  ground truth before distribution.
- **Four carriers**, one shared rule and meta schema: rendered (text), preserved (text
  PDFs), raster (scanned/image-only PDFs), and vector (outline-text PDFs). Scanned and
  vector documents keep tables, figures, stamps, and layout pixel-identical / byte-exact.
- **Fingerprint Desk web app** (FastAPI, single process): Google sign-in, campaigns with
  assigned mode, capacity guards, simulated-leak preview, per-contributor pooled verdicts,
  ground-truth-gated file serving, admin dashboard, and corpus export.
- **No-account volunteer pack flow**: contribute with only a printed pack code; per-sheet
  verdicts withheld until every sheet has a readable capture (blind protocol preserved).
- **Metrics/guarantee chain** (`metrics.py`): symbol-error rate, effective symbol count,
  and the tier mapping (courtroom / strong lead / weak lead / no guarantee).
- **Harness & tooling**: corpus bakeoff scaffold, channel simulator, submission-scoring
  pipeline, and the `sim300` stress test.
- **Deployment**: Dockerfile + docker-compose + Caddy (automatic HTTPS), `.env.example`,
  and CI running the metrics, app, demo, and scoring self-tests.

### Validation
- Rendered carrier validated on a **real** print → photo capture (14/15 line bits).
- Preserved (text-PDF) carrier validated on the **simulated** channel only.
- Raster and vector carriers exercised against real-world third-party documents: a
  scanned, image-only examination paper (two-column, ~109 dpi, real skew) and an
  outline-text examination PDF (~1,300 vector paths per page). Those source documents are
  third-party copyrighted material and cannot be redistributed, so they are not included in
  this repository. Decoding in both cases used the simulated channel, not a real
  print-and-photograph capture. Real-capture validation for these two carriers is pending
  the corpus campaign.
- The simulated channel is never reported as a real result; a real print → photograph →
  messaging corpus is being collected.

[0.1.0]: https://github.com/En10-Pvt-Ltd/fingerprint-desk/releases/tag/v0.1.0
