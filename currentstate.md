# Current State — Forensic Document Fingerprinting

_Audit date: 2026-07-26 · branch `claude/crowdsource-demo` (merged to `main` at `3d93d12`/`3943732`)_

## 1. What this project is

Research code plus a public web application for **forensic document
fingerprinting**: invisible, per-copy codewords embedded in the *geometry*
of a printed page (line-shift and word-shift, the Brassil family). Each
printed copy carries a slightly different, imperceptible pattern of
sub-millimetre nudges. A photograph of a leaked page — taken on a phone,
optionally pushed through WhatsApp — is decoded **blind** (no original, no
fiducials) to identify which copy leaked, with a stated false-accusation
probability.

Two things distinguish it from prior art (see `docs/technology-comparison.md`):
it needs only an ordinary phone photo to read (not a scanner or blue light,
unlike yellow-dot MIC or halftone stego), and it ships an explicit
statistical guarantee with a hard "no false accusations" discipline rather
than a bare match/no-match.

The academic framing is in `spec-v0.3-delta.md`. Work is staged in priority
order (smoke test → corpus harness → public app), and the code mirrors that.

## 2. The forensic method

**Public encoding convention** (identical on encode and decode sides;
`encode.py`, `decode.py`):

- 300 dpi render, serif font, ~45 lines/page.
- **Line-shift**: lines run in triplets `(control, marked, control)`; only
  the middle line carries a bit, its baseline shifted ±`LINE_SHIFT = 2 px`
  (1/150 in). ~15 line bits/page.
- **Word-shift**: only odd interior word slots carry bits; gap redistributed
  `gap_before += d; gap_after -= d` at `WORD_SHIFT = 3 px` (1/100 in).
  ~273 word bits/page. (Rendered carrier only.)
- **Sign-only decisions**: decode reads only the *sign* of a differential,
  so it is scale-free across capture resolutions.
- 64-bit PRN payload from a seed, embedded with repetition + majority vote.

**Attribution rule** (`app/engine/scan.py`, one rule shared by all carriers):
claim a source only when the best variant's exact binomial p-value against
chance, **Bonferroni-corrected for the number of variants**, is
≤ `P_THRESHOLD = 1e-3` **and** at least `MIN_BITS = 10` symbols were observed
**and** the top candidate beats the runner-up by a margin of
`max(4 bits, 8% of observed bits)`. Otherwise the verdict is an honest
**no-attribution** — treated as a first-class correct answer (e.g. for a
control page). A control crossing the threshold is a campaign-failing event.

## 3. Carrier family — four ways to fingerprint a document

All carriers share the triplet convention, the meta schema, and the
attribution rule; they differ only in *where* the shift is applied. The app
auto-detects which carrier fits an uploaded PDF (text → preserved → raster →
vector fallback chain in the isolated worker).

| Carrier | Mode | Input it handles | Engine | How it marks | Status |
|---|---|---|---|---|---|
| **Rendered** | `rendered` | pasted text / extracted PDF text | `render.py` + `encode.py`/`decode.py` | app re-typesets and shifts lines+words | Validated on a **real** phone capture (14/15 line bits, 0.933) |
| **Preserved** | `pdf_preserved` | text PDFs (formatting kept) | `pdf_mark.py` / `pdf_scan.py` / `scan_pdf.py` | edits text-showing ops in the content stream | Validated on synthetic + WhatsApp channel sim |
| **Raster** | `pdf_raster` | scanned / image-only PDFs | `raster_mark.py` / `scan_raster.py` | nudges pixel-row strips of the page image (±2 px), re-embedded losslessly | Field-tested on a scanned NEET paper (synthetic decode) |
| **Vector** | `pdf_vector` | outline-text PDFs (glyphs as paths) | `vector_mark.py` / `scan_raster.py` | translates each line's paths ±0.48 pt in the content stream | Field-tested on a CBSE Accountancy paper (synthetic + WhatsApp sim) |

Key properties preserved by the two no-text carriers: everything outside a
shifted line stays **pixel-identical** (raster) or **byte-exact vector**
(vector), so tables, figures, stamps, and two-column layouts survive; the
control copy is always a byte copy of the source; and both decode through the
raster pathway's meta-guided sub-pixel profile-correlation decoder unchanged.

**Field tests present in-repo:**
- `field-test-003-neet-raster/` — 31-page scanned NEET paper (image-only,
  ~109 dpi, two-column, real skew); 9 slots across pages 0–4.
- `field-test-004-accountancy/` — 32-page outline-text CBSE Accountancy paper
  (~1,300 paths/page); 31 slots across pages 1–4.

## 4. The application — "Fingerprint Desk"

A single-process FastAPI app (`app/serve.py`) over the research pipeline.
SQLite + an in-process job queue + CPU-bound OpenCV decoding — deliberately
one worker.

**Owner/contributor flow (authenticated):** Google sign-in (dev sign-in form
locally) → paste text or upload a PDF → the app auto-detects the carrier and
previews capacity → generate N fingerprinted variants + 1 unmarked control,
sealing a SHA-256 **commitment** over ground truth → share the campaign
(open or *assigned* mode, one unique variant per contributor) → contributors
print, photograph, upload → blind decode returns a plain-language verdict →
contributor confirms the truth (they know which copy they printed), producing
the ground-truth label. A **pooled verdict** combines the best photo of each
page (same-page photos don't double-count).

**HTTP surface (26 app routes + 5 auth routes), notable ones:**
- `POST /api/analyze-pdf` — carrier auto-detection + capacity, untrusted PDF
  parsed only in the isolated child process.
- `POST /api/tests` / `GET /api/tests/{id}` / `/verify` / `/pdf/{doc}` /
  `/scan` / `/simulate` / `/feedback` — the test lifecycle.
- `GET /api/files/{id}/{subpath}` — ownership-gated; ground-truth metas are
  **never** servable.
- Assigned campaigns: `/api/campaigns`, `/join`, `/funnel`.
- Admin: `/api/admin/stats`, `/contributions`, `/export`, `/tests/{id}/share`.
- Pack flow (no auth): `GET /api/packs/{id}`, `POST /api/packs/{id}/scan`,
  `GET /packs/{zip}`.

**Persistence:** artifacts as plain files under `appdata/tests/<id>/`;
`users / tests / scans / feedback / events / assignments` in SQLite
(`app/engine/db.py`). Commitment binds metas + emitted PDF bytes.

**Metrics/guarantee chain (`metrics.py`):** `ser`, `k_eff` (effective
observed-symbol count), `epsilon1`/`tier` mapping `(c, k, p, n, β)` to an
achievable false-accusation probability and a tier label (courtroom / strong
lead / weak lead / no guarantee), surfaced at `GET /api/tiers`.

## 5. No-account volunteer pack flow

Pre-generated print packs (`app/tools/make_volunteer_packs.py`) — three
sheets each (two marked variants + one control, shuffled to A/B/C) — let
volunteers contribute with **only the pack code printed on the sheet**: no
account, no Supabase, in-app decoding. Ground truth stays private under
`appdata/volunteer_packs/<id>/private/` and is never served.

Integrity rule: per-sheet verdicts are **withheld until all three sheets have
a readable capture**, so a volunteer can't learn mid-experiment which sheet
is the control. The reveal report gives a plain-language outcome per sheet
(`read-correct`, `read-wrong`, `unreadable`, `control-passed`,
`control-false-alarm`).

The frontend (`app/static/`) is one merged SPA carrying the recruitment/
landing content and the app; the standalone `demo/` Netlify site (with an
optional Supabase magic-link volunteer portal) still exists and banners
volunteers toward the in-app flow.

## 6. Security posture

Reviewed twice (security + correctness) before the last merge; all findings
resolved. Verified properties:

- Untrusted PDF bytes parse **only** in `engine.pdf_worker`, a subprocess
  with `RLIMIT_AS` + a wall-clock timeout and a scrubbed env; never in the
  server process.
- CSRF (double-submit token) on every authenticated mutating endpoint;
  pack endpoints are intentionally CSRF-exempt and derive no session
  authority (capability = the URL pack code).
- Ownership/assignment gating on files, PDFs, scans, feedback, funnel;
  ground-truth metas and seeds are stripped from non-owner views and
  unservable as files. Path traversal blocked; pack tests live outside the
  ownership DB so their truth metas are unreachable.
- Uploads capped (size, pixel count, min resolution) behind a shared
  validator; dev-login is triple-gated off for the production config.
- Pack surface hardened: per-pack capture cap, per-client rate limits (the
  app trusts the proxy's `X-Forwarded-For` only when `FF_TRUST_PROXY=1`,
  set in the shipped compose because the app port is never published), and
  unguessable random pack codes.

## 7. Testing & CI

- **`app/selftest.py`** — end-to-end over the live API via FastAPI
  TestClient, throwaway `FF_APPDATA`. **167 checks** across 20 sections
  `[0]`–`[16]`, covering auth/CSRF/ownership, generation + commitment,
  simulated + real-capture attribution, the margin rule / resolution gate /
  pooled verdict, all four carriers (rendered, preserved, rich-content,
  raster/vector), quotas, shared + assigned campaigns, corpus export, and the
  full pack flow with the reveal gate and capture cap. Requires a **serif**
  font via `FF_FONT_PATH` (the default path is Linux-only).
- **`metrics.py`** self-test reproduces the spec's worked tier cells.
- **`.github/workflows/ci.yml`** — metrics self-tests, the app selftest, the
  demo-site verification gate, and the submission-scoring selftest on a plain
  Ubuntu runner.
- **`app/tools/score_submissions.py`** — offline weekly scoreboard from
  volunteer captures, reusing the app's validated scoring path verbatim, with
  pre-registered quality gates and control-FPR surfacing.

## 8. Deployment

- `Dockerfile` (single process, `CMD python app/serve.py`), `docker-compose.yml`
  (app + Caddy; only Caddy publishes 80/443), `Caddyfile` (automatic HTTPS).
- `.env.example` documents `SECRET_KEY`, `BASE_URL`, `GOOGLE_CLIENT_ID/SECRET`,
  `ADMIN_EMAILS`; `/data` is the persistent volume (SQLite + sealed
  commitments — the thing to back up).
- Recommended target: one small VPS (`docker compose up -d`). The Supabase/
  Netlify volunteer portal is now **optional** — the pack flow runs entirely
  in-app.
- Supabase MCP server + agent skills are configured in-repo (`.mcp.json`,
  `.agents/skills/`) but auth is per-user and not required to run the app.

## 9. Important caveat on "validated"

Per `CLAUDE.md`, **the synthetic channel is never a result.** The single
real-world go/no-go so far is the rendered-carrier smoke test
(`received.jpeg`, a real print→photo, 14/15 line bits). The three PDF
carriers (preserved, raster, vector) are validated on the **synthetic channel
and the app's WhatsApp channel simulation** and on real *source documents*,
but have **not yet been through a real print → photograph → messaging-app
capture**. That end-to-end real-capture corpus is exactly what the volunteer
pack flow exists to collect.

## 10. Known limitations & backlog

Non-blocking items surfaced in review, not yet done:

- **Marked-page span**: no-text carriers mark only the first ≤5 pages; long
  documents need a photo of one of those pages (or the default raised).
- **Candidate-page selection**: `scan_raster.py` picks the page by strength
  of evidence; `scan_pdf.py` still uses raw accuracy (port pending).
- **Bonferroni** corrects for variant count but not for best-of-≤5 page
  selection (mild FPR inflation).
- Provisioner idempotency is scoped to the dev-shim user; `new_test_id` has a
  small (2-byte) collision window; `sim300/run_sim.py` reporting can overstate
  by counting engine errors as clean abstentions and omitting the margin rule.
- Minor UI robustness: generation-poll error handling, quota TOCTOU, unvalidated
  legacy `mode` values elsewhere.

## 11. Capability summary

| Capability | State |
|---|---|
| Embed/decode geometric fingerprint (line + word shift) | ✅ core, real-capture validated (rendered) |
| Fingerprint text PDFs preserving layout | ✅ app, sim-validated |
| Fingerprint scanned / image-only PDFs | ✅ app, field-tested (raster) |
| Fingerprint outline-text ("secure") PDFs | ✅ app, field-tested (vector) |
| Blind phone-photo decode + WhatsApp survival | ✅ (sim + one real rendered capture) |
| Statistical attribution with FPR discipline | ✅ p≤1e-3, ≥10 bits, margin rule |
| Public app: auth, campaigns, assigned mode, admin | ✅ reviewed & hardened |
| No-account volunteer pack flow with reveal gate | ✅ shipped |
| Corpus export → offline scoreboard | ✅ shipped |
| Containerised deploy (VPS + Caddy HTTPS) | ✅ ready |
| Real print→photo→messaging corpus at scale | ⏳ pending (volunteer launch) |
