# Current State — Forensic Document Fingerprinting

_Audit date: 2026-07-26, refreshed 2026-07-30 through the FF_MODE auth redesign,
the recovery key + commitment receipt, roster/count campaigns (300 cap) with the
pre-distribution seal, and bulk ZIP download._

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
| **Preserved** | `pdf_preserved` | text PDFs (formatting kept) | `pdf_mark.py` / `pdf_scan.py` / `scan_pdf.py` | edits text-showing ops in the content stream | Synthetic + WhatsApp sim, plus one limited real capture (`field-test-002/`, 1 of 2 doc classes passed) |
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

**Auth (FF_MODE):** two modes only — `local` (no accounts; the implicit
operator is admin; loopback-only) and `server` (email+password local accounts;
a one-time first-run screen creates the admin; further accounts via single-use
invite links). Google sign-in and the dev-login shim were removed in the
FF_MODE redesign; `ADMIN_EMAILS` is a bootstrap seed only.

**Owner flow:** sign in → paste text or upload a PDF → auto-detect carrier +
preview capacity → name the copies (**Quick** 2–5, or admin **count**/`{n}`
pattern / **roster** paste/CSV, up to 300) → generate variants + 1 unmarked
control, sealing a SHA-256 **codebook commitment**; a roster/count campaign
also binds who-gets-which at creation (`pre_distribution` seal), a join
campaign binds it as recipients claim copies (`snapshot`) → distribute (per-copy
PDF, or **Download all copies (ZIP)**) → leaked photo uploaded → blind decode
returns a plain-language verdict, naming the recipient for roster/imported
campaigns → contributor confirms the truth (join campaigns). A **pooled
verdict** combines the best photo of each page.

**Recovery key + receipt:** any campaign can export a self-contained recovery
key (`<id>.fdkey.json`, encrypted at rest by default — Argon2id + AES-256-GCM)
and a small commitment receipt; a key imported on another install investigates
a leak and names the recipient, even if the original data directory is gone.

**HTTP surface, notable ones:**
- `POST /api/analyze-pdf` — carrier auto-detection + capacity, untrusted PDF
  parsed only in the isolated child process.
- `POST /api/tests` (roster/count aware) / `GET /api/tests/{id}` / `/verify` /
  `/pdf/{doc}` / `/scan` / `/simulate` / `/feedback` — the test lifecycle.
- Recovery: `/api/tests/{id}/recovery-info` / `/recovery-key` / `/receipt`,
  `POST /api/import-recovery-key`; `GET /api/tests/{id}/copies.zip` (bulk).
- `GET /api/files/{id}/{subpath}` — ownership-gated; ground-truth metas are
  **never** servable.
- Assigned campaigns: `/api/campaigns`, `/join`, `/funnel`.
- Admin: `/api/admin/stats`, `/contributions`, `/export`, `/tests/{id}/share`,
  `/invite`.
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
  validator. Server mode uses Argon2id passwords, generic login errors (no
  user enumeration), per-IP + per-email login rate limits, single-use expiring
  invites, and session regeneration on login.
- Pack surface hardened: per-pack capture cap, per-client rate limits (the
  app trusts the proxy's `X-Forwarded-For` only when `FF_TRUST_PROXY=1`,
  set in the shipped compose because the app port is never published), and
  unguessable random pack codes.

## 7. Testing & CI

- **`app/selftest.py`** — end-to-end over the live API via FastAPI
  TestClient, throwaway `FF_APPDATA`. **293 checks** across sections
  `[0]`–`[16]`, covering auth/CSRF/ownership, generation + commitment,
  simulated + real-capture attribution, the margin rule / resolution gate /
  pooled verdict, all four carriers (rendered, preserved, rich-content,
  raster/vector), quotas, shared + assigned campaigns, corpus export, and the
  full pack flow with the reveal gate and capture cap. Uses the bundled
  Liberation Serif (SIL OFL) by default on every OS; override with a serif
  `FF_FONT_PATH` only if you want a different face.
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
- `.env.example` documents `SECRET_KEY`, `BASE_URL`, `FF_MODE`, `ADMIN_EMAILS`
  (Google sign-in was removed in the FF_MODE auth redesign); `/data` is the
  persistent volume (SQLite + sealed commitments — the thing to back up, or
  export a per-campaign recovery key as a portable backup).
- Recommended target: one small VPS (`docker compose up -d`). The Supabase/
  Netlify volunteer portal is now **optional** — the pack flow runs entirely
  in-app.
- Supabase MCP server + agent skills are configured in-repo (`.mcp.json`,
  `.agents/skills/`) but auth is per-user and not required to run the app.

## 9. Important caveat on "validated"

Per `CLAUDE.md`, **the synthetic channel is never a result.** Two carriers
have a real print → photograph → messaging capture so far: the rendered-carrier
smoke test (`received.jpeg`, 14/15 line bits) and the **preserved** carrier
(`field-test-002/`, a real print → phone photo → WhatsApp hop via
`app/m3_check.py`). The preserved result is deliberately *limited*: of two
document classes, only `times11` passed the M3 gate (aggregate 37/41 = 0.902,
page-1 14/14 and 13/14, control at chance 29/54 = 0.537); the 10 pt
heading-heavy class did **not** validate and is recorded as such, and some
segmentation filters were partly post-hoc — see `field-test-002/README.md`.
The **raster** and **vector** carriers are validated only on the **synthetic
channel and the app's WhatsApp channel simulation** and on real *source
documents*, and have **not yet** been through a real print → photograph →
messaging capture. Broadening all of this end to end is exactly what the
volunteer pack flow and corpus campaign exist to collect.

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
