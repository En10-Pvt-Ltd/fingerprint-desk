# Fingerprint Desk

Public crowdsourcing app over the research pipeline: contributors sign in
(server mode: invite-only email+password accounts), download one of up to
5 fingerprinted variants (their secret pick), print it, photograph it,
upload the photo, and confirm whether the blind decoder named the right
variant. Each confirmed answer is a ground-truth label and each photo a
real-channel capture for the Part-B corpus.

## Run (local mode — single operator, no accounts)

```
pip install -r requirements.txt -r app/requirements.txt
python app/serve.py       # -> http://localhost:8765
```

With `FF_MODE` unset and the default loopback bind this is **local mode**:
every request acts as the implicit local operator (an admin); the server
refuses to bind to anything but loopback. Rendering uses the bundled Liberation
Serif font, so no font setup is needed on any OS (override with `FF_FONT_PATH`
only for a deliberate font experiment).

## Deploy (VPS — server mode)

```
cp .env.example .env      # set SECRET_KEY, DOMAIN, BASE_URL
docker compose up -d      # app + Caddy (automatic Let's Encrypt TLS)
```

Docker deployments run in **server mode** (`FF_MODE=server`, pinned in
docker-compose.yml): the first visit shows a one-time setup screen that
creates the admin account, and further accounts are minted as single-use
invite links from `/admin`. (Google sign-in was removed; a hosted mode may
reintroduce OAuth in a later phase — see MIGRATION.md.) All state lives in
`./data` (SQLite `app.db` + `appdata/` file store) — back that directory
up.

## Crowdsourcing model

- **Campaigns**: an admin creates a test and clicks "Share with all
  contributors". Every signed-in user then sees it under "Join a test" and
  skips straight to download → print → photograph. Contributors only ever
  see their own scans.
- **Assigned campaigns**: sharing with `{"assigned": true}` turns the
  campaign into assigned mode: each contributor `POST
  /api/campaigns/{id}/join`s and is atomically handed the lowest unassigned
  *marked* variant (controls are never assigned; re-join returns the same
  variant; a full campaign answers 409). A contributor then sees and can
  download only their own variant; `GET /api/tests/{id}/funnel` gives the
  owner the variants → assigned → uploaded → feedback funnel. Admins may
  create up to `FF_MAX_CAMPAIGN_VARIANTS` (default 300) variants
  (self-serve tests keep the cap of 5); create/share responses carry a
  `capacity_warning` when the variant count risks a false match on a
  short document (union bound over `Binomial(15·pages, 0.5)` at the 0.93
  attribution accuracy, >1% flagged).
- **Feedback**: after each real-photo scan the contributor answers
  correct / wrong (naming the true variant when wrong). Stored in SQLite
  and mirrored as `feedback.json` beside the scan.
- **Export**: `/admin` shows totals and streams a zip of labeled captures
  with intake.py-style sidecars (`synthetic: false`, unknown fields as
  `crowd_unknown`) for the corpus harness.
- **Hardening**: Argon2id local accounts (server mode) + CSRF, login rate
  limiting, per-user ownership on every route,
  ground-truth metas never servable, upload size/page caps, untrusted PDFs
  parsed in a memory-limited child process, bounded generation/scan
  workers, per-user daily quotas.

## Contributor flow (guided wizard)

1. **Upload** (or join a campaign and skip this): upload a PDF. If its
   layout can carry the line-shift mark it is fingerprinted in place
   (formatting preserved); otherwise its text is extracted and re-typeset
   through the app's layout engine, explained in plain language. Pick 2-5
   copies; one unmarked control is always added. The capacity check warns
   when pages are too short for real-photo attribution. The full codebook
   is sealed under a SHA-256 commitment at generation time.
2. **Print**: download one variant — the contributor's secret pick — and
   print at 100% scale on a laser printer (control too, if possible).
3. **Photograph**: upload a phone photo (optionally after WhatsApp), with
   optional printer/phone/lighting dropdowns matching the corpus enums.
   Photos under `FF_MIN_CAPTURE_PX` (default 1200) on the longest side are
   rejected up front with retake guidance — they carry too little detail
   (real WhatsApp photos at ~1600 px pass). The blind decoder identifies
   the page, scores every variant, and attributes only when (a) the
   Bonferroni-corrected binomial p-value clears 1e-3 over at least 10
   observed symbols and (b) the top candidate beats the runner-up by at
   least max(4 bits, 8% of observed bits) — near-ties abstain with a
   plain-language "two copies match too closely" reason instead of
   guessing. When a contributor has 2+ real photos of a test, the test
   page also shows a **combined reading** (`pooled_verdict`): per-candidate
   bit agreements pooled across all their photos (photos of different
   pages add their bits), with the same p/min-bits/margin rule applied to
   the totals — pooling is near-perfect even where single photos are
   marginal, so contributors are encouraged to photograph every page.
4. **Confirm**: the result card asks "were we right?" — correct / wrong
   (+ the true variant when wrong). Raw score tables stay behind a
   collapsed "Technical details" block.

## Verify

```
python app/selftest.py
```

End-to-end self-test (299 checks) run in server mode (FF_MODE=server)
against a throwaway FF_APPDATA: the original research-pipeline checks
(layout, generation, commitment, simulated leaks, control credibility,
PDF modes, the Phase A real-capture regression at line-shift 0.933) plus
the server-mode auth surface (first-run setup creates exactly one admin,
email+password login with one generic failure message, bad-login rate
limiting, single-use expiring invites, non-admins blocked from admin
routes), the local-mode loopback-guard helper, CSRF, ownership isolation
(tests, PDFs, files, scans), the never-servable ground-truth metas, the
5-variant cap, quotas, feedback round-trip, shared campaigns, assigned
campaigns (join / assignment isolation / funnel / capacity warning), the
corpus export zip, the runner-up margin rule (both simulated wrong-variant
near-ties abstain, clean reads still attribute), the minimum-resolution
gate, overflow-safe pooled binomial tails past 1023 bits, and the pooled
per-contributor verdict endpoint.

## Honest limits (also shown in the app footer)

Retyping defeats any watermark. Leaks before copies are differentiated are
invisible. The smoke-scale decoder needs full-page captures; fragments are
out of scope here. Simulated-channel results demonstrate decoder logic, not
field performance; the physical validation status lives in the research
repo (one real print-photo-WhatsApp capture pair, line-shift 0.933 GO,
control at chance, corpus campaign pending).

## How it reuses the research code

`encode.py` was refactored (behavior-preserving, output bit-identical) to
expose `wrap_words` / `render_page`; the app renders multi-page custom text
through those same functions. Scanning reuses `decode.py`'s deskew /
segmentation / baseline / gap readers and `robust_decode/run_robust.py`'s
crop + flat-field + autocorrelation path for real photos. The synthetic
channel runs `channel.py` itself via subprocess. Nothing else in the
research pipeline was modified.
