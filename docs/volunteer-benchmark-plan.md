# Volunteer wild-corpus campaign: plan, budget, and launch kit

*(Companion code: `app/tools/make_volunteer_packs.py`, `demo/volunteer.html`
+ `demo/volunteer.js`, `docs/volunteer-portal/schema.sql`. This document is
the operator's manual and the campaign copy, in one place.)*

## 1. What crowdsourcing can and cannot do here — an honest rating

The spec's benchmark is a **controlled corpus**: 35 physical documents,
known printers and paper stocks, ~1,200 captures over sampled
(phone × angle × lighting × framing) cells, frozen splits, no shared
physical page between tuning and reporting. Volunteers cannot replace
that — you don't control their printers, and you can't verify their
protocol compliance. What volunteers give you is the thing the controlled
rig can never afford: **diversity**. Fifty volunteers means ~30–50 distinct
printer models and ~50 phone cameras, which is exactly the axis on which
the current evidence is thinnest (one printer, a few phones).

**Rating the approach: 7/10** as a *complement*, 3/10 as a *replacement*.
Run both, report them separately, and label them: the controlled corpus
produces the tier-table constants; the wild corpus produces the
generalization claim ("held across N printers and M phones in the wild").
Rules that keep it honest:

- Volunteers photograph **our generated test sheets** (the pack tool uses
  the repo's own encoder) — never real or copyrighted exam papers.
- Ground truth (which sheet is marked, with which codeword) never leaves
  the repo; sheets are anonymized A/B/C per pack with a private mapping.
- Quality gates on ingest: EXIF sanity (came from a camera), decode-side
  segmentation validity gates (already built — they reject foreign
  documents), duplicate-image hashing, and per-volunteer consistency
  checks. Junk or protocol-violating submissions are excluded *by rule,
  stated in advance*, not by looking at the outcome.
- Unmarked controls ride along in every pack, so the FPR-must-be-zero
  discipline extends to the wild corpus unchanged.
- The wild corpus never enters the tuning split. It is report-only.

## 2. Architecture (what the scaffold implements)

| Concern | Choice | Cost |
|---|---|---|
| Landing + portal | existing Netlify demo site + `volunteer.html` | $0 |
| Login | Supabase Auth magic-link email (no passwords) | $0 |
| Database | Supabase Postgres (`packs`, `captures`, RLS) | $0 |
| File storage | Supabase Storage, private `captures` bucket | $0 (1 GB) |
| Sign-in email | Supabase built-in mailer (rate-limited) | $0 |
| Announcement email | not needed at this scale; use Resend free tier if wanted | $0 |
| Pack generation & scoring | offline in this repo (no server compute at all) | $0 |

Setup is ~30 minutes: create Supabase project → run `schema.sql` → create
the private `captures` bucket → paste URL + anon key into `volunteer.js`
→ run `make_volunteer_packs.py --n 25` → deploy `demo/` (packs ship as
static zips) → insert pack rows.

## 3. The $50 budget

| Item | Cost | Verdict |
|---|---|---|
| Hosting, auth, DB, storage, email (above) | $0 | free tiers cover a 50–100 volunteer campaign |
| Domain (optional, e.g. `paperfingerprint.org`) | ~$12/yr | worth it: a real domain roughly doubles click-through from social posts |
| Supabase Pro for ONE month | $25 | only if storage passes 1 GB (≈ 60+ volunteers uploading full-size originals); decide when the dashboard says so, not before |
| Reserve | $13–38 | print-and-post a pack to 2–3 high-value volunteers who lack printers, or a small thank-you draw |
| Paid ads | $0 | $50 of LinkedIn/Reddit ads buys ~2k low-intent impressions — worthless next to one good organic post. Spend attention, not money. |

## 4. The volunteer ask (put this everywhere, verbatim)

> **15 minutes, a printer, a phone, WhatsApp.** Print 3 test sheets,
> photograph them, send the photos through WhatsApp, upload both versions.
> That's it. You'll be helping build the first open benchmark for
> leak-tracing document fingerprints — the technology that could make
> exam-paper leaks attributable.

## 5. LinkedIn launch kit

**Post 1 — the story (post from your personal account):**

> In 2024, India's NEET medical entrance papers leaked before exam day.
> Photographs on WhatsApp, millions of students affected — and no way to
> prove *whose copy* was photographed, because every copy looks identical.
>
> For the past months I've been building the answer: invisible fingerprints
> in the print geometry itself. Each copy's lines sit a quarter-millimeter
> differently — invisible to you, decodable from a WhatsApp photo of the
> printed page. In lab tests it survives print → phone photo → WhatsApp at
> over 90% accuracy, with a statistical guarantee against accusing the
> wrong person.
>
> Now it needs the test that matters: **your** printer, **your** phone.
> I'm looking for 50 volunteers with 15 minutes, a printer, and WhatsApp.
> Print 3 sheets, photograph, upload. Every capture goes into an open
> research corpus.
>
> Link in comments. (And yes — the leaked-looking sheets you'd be
> photographing are generated test documents, not real papers.)

**Post 2 — the technical thread (2–3 days later):**

> How do you hide a serial number in a printed page so that it survives a
> phone camera AND WhatsApp compression — but a human can't see it?
> Not watermarks. Not yellow dots (those identify printers, wash out in
> photos, and are strippable). You move entire *lines of text* by ~250
> microns... 🧵
> [3–5 short follow-ups: the triplet trick, the sign-only decoder, the
> false-accusation math, ending with the volunteer link]

Cadence: post 1, then the thread, then a weekly progress update with a
real chart ("34 volunteers, 19 printer models, accuracy by phone tier so
far") — progress updates recruit better than the launch post. Tag/DM:
IIT/IISc information-security faculty, ed-tech and exam-integrity people,
and anyone who commented on NEET-leak coverage.

## 6. Reddit launch kit

Read each subreddit's self-promotion rules first; message mods before
posting anywhere that requires it. Never post the same text twice.

- **r/SampleSize** (built for this): title —
  *"[Casual] Help test anti-leak document fingerprints: print 3 sheets,
  photograph, WhatsApp them (15 min, need: printer + phone)"*. Body: the
  ask, what the data is for, CC0/consent note, link.
- **r/datasets**: frame as dataset building — *"Building an open corpus of
  print→phone→WhatsApp document captures for forensic watermarking
  research — contribute 6 photos"*. This crowd cares about the corpus
  being downloadable later: promise (and deliver) an open release.
- **r/india or r/developersindia** (mods permitting): lead with the NEET
  problem, not the tech: *"After the NEET leaks I built invisible
  fingerprints that survive WhatsApp — help me prove it works on Indian
  printers and phones"*. Expect (and welcome) skeptical top comments —
  answer them with the control-experiment numbers; skepticism answered
  well is the best recruiting content on Reddit.
- Engagement rule: reply to every substantive comment in the first 3
  hours; offer an informal AMA in-thread. Do not link-drop and leave.

## 7. What "success" is

- **Floor:** 25 volunteers × 3 sheets × 2 files = 150 captures across
  ~20 printers. Enough for a printer-diversity table in the paper.
- **Target:** 60–80 volunteers ≈ 400–500 captures — the wild corpus
  becomes a headline result on its own.
- Every submission gets scored offline against its pack's private ground
  truth; publish a live aggregate (accuracy by phone tier / lighting /
  framing, controls at chance, zero false accusations) — that public
  scoreboard *is* the campaign's engine after week one.

## 8. Consent, privacy, integrity (non-negotiables)

- Email used for sign-in and bookkeeping only; never published; deleted on
  request. Uploads are CC0 by explicit checkbox, stated at upload time.
- Uploads contain only our generated sheets; anything else is excluded and
  deleted.
- The wild corpus is report-only (never tunes thresholds), quality gates
  are pre-registered in this document, and the eventual public dataset
  release ships with the same sidecar metadata schema the controlled
  corpus uses (`corpus_config.json` vocabulary).
