# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Generate-time self-verify guard.** After a campaign's copies are made, the app decodes
  each copy's own clean render through the same decoder an investigation uses and **refuses to
  create the campaign** (fail closed, no override) if the true copy does not read back — so an
  operator can never print and distribute a document that could never trace a leak. The
  refusal names the cause (marks unreadable on this document type vs. too few markable marks),
  since the remedies differ. Every campaign is now verified against its specific document,
  rather than relying on the reader to heed document-choice guidance.
- **Per-campaign recovery key + commitment receipt.** A campaign's ground truth can be
  exported as a portable, optionally-encrypted (Argon2id + AES-256-GCM) `<campaign>.fdkey.json`
  and imported on another installation to investigate a leak — naming the recipient, not just
  a copy id — even if the original data directory is gone. A small commitment receipt (digests
  + seal, no ground truth) is meant for third-party escrow before distribution. Import is
  integrity-first and transactional; imported campaigns are investigation-only. Format:
  `docs/recovery-key-format.md`.
- **Keyed commitment (v2)** binding the who-received-which mapping and its seal kind
  (`pre-distribution` vs `snapshot`) in addition to the codebook commitment.
- **Two explicit deployment modes** (`FF_MODE=local` loopback-only / `FF_MODE=server`
  email+password accounts with first-run setup and single-use invites); see `MIGRATION.md`.
- **Bundled Liberation Serif font** (SIL OFL 1.1) as the default render face, so a fresh
  clone renders identically on any OS with no font setup.

### Changed
- `ADMIN_EMAILS` is now a bootstrap seed only, not a live admin check (closes a privilege
  escalation). Admin status lives in the database.

### Removed
- Google sign-in and the `authlib` dependency (a hosted OAuth mode may return later).

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
  print-and-photograph capture. Note: the scanned raster paper carries only 9 markable
  slots — below the 10-bit attribution minimum — so it demonstrates the raster mechanism but
  the generate-time self-verify guard would refuse a campaign built from it; it is not
  attribution-grade evidence. Real-capture validation for these two carriers is pending
  the corpus campaign.
- The simulated channel is never reported as a real result; a real print → photograph →
  messaging corpus is being collected.

[0.1.0]: https://github.com/En10-Pvt-Ltd/fingerprint-desk/releases/tag/v0.1.0
