# Go-live checklist (~30 minutes)

Everything below is one-time. When you finish, the volunteer page is live
and self-serving; scoring stays offline in this repo.

## 1. Supabase (~12 min)

1. Sign up / log in at supabase.com and **create a new project** (free
   tier, any region near your volunteers; note the database password it
   asks you to set, though you won't need it day-to-day).
2. Open **SQL Editor**, paste the entire contents of
   `docs/volunteer-portal/schema.sql`, and run it. It should finish with
   no errors.
3. Open **Storage**, create a bucket named exactly `captures`, and leave
   **Public bucket OFF** (the schema's policies handle access).
4. Open **Authentication > Sign In / Up > Email** and make sure Email
   sign-in with magic links / OTP is enabled (it is by default).
5. Open **Project Settings > API** and copy two values: the **Project
   URL** and the **anon public** key.

## 2. Wire the frontend (~3 min)

1. In `demo/volunteer.js`, replace `PASTE_SUPABASE_URL_HERE` and
   `PASTE_SUPABASE_ANON_KEY_HERE` with the two values. (The anon key is
   designed to be public; row-level security protects the data.)
2. Commit the change.

## 3. Register the packs (~5 min)

The 25 packs are already generated (`demo/packs/pack_FP001.zip` through
`pack_FP025.zip`; ground truth in `appdata/volunteer_packs/`, which is
never deployed). Register them in the database: in the Supabase SQL
editor run the insert that `demo/packs/index.json` describes, i.e.

    insert into public.packs (pack_id, url) values
      ('FP001', 'packs/pack_FP001.zip'),
      ('FP002', 'packs/pack_FP002.zip'),
      -- ... through ...
      ('FP025', 'packs/pack_FP025.zip')
    on conflict (pack_id) do nothing;

(Generate more later with
`python app/tools/make_volunteer_packs.py --n 50` and insert the new
rows; existing packs are regenerated identically thanks to fixed seeds.)

## 4. Deploy (~5 min)

Redeploy the `demo/` directory to Netlify exactly as before (the packs
ship as static files with the site). Then run the repo gate:

    python check_site.py

and click through the live site once: the volunteer page should show the
sign-in card WITHOUT the yellow "not configured" banner.

## 5. Smoke-test the loop (~5 min)

1. On the live volunteer page, sign in with your own email (magic link).
2. Confirm you're assigned pack FP001 and the zip downloads.
3. Submit a dummy capture (any photo) with the consent box ticked.
4. In Supabase: the row appears in `captures`, the files appear in
   Storage under your user id. Delete the dummy row + files afterwards.

## 6. Launch

Post using the drafts in `docs/volunteer-benchmark-plan.md` (LinkedIn
story post first, technical thread two or three days later, Reddit per
the sub-rule cautions). Then keep the weekly scoreboard cadence: pull
submissions, score them offline against
`appdata/volunteer_packs/<id>/private/`, and post the aggregate.

## Scoring submissions offline (whenever you like)

1. Download the `captures` table as CSV (Supabase table editor) and pull
   the bucket (Storage UI, or the CLI shown at the bottom of schema.sql).
2. For each capture row: its pack + sheet letter maps to ground truth via
   `appdata/volunteer_packs/<pack_id>/private/mapping.json`; decode the
   image with the robust pipeline against `<role>_meta.json` and score
   marked sheets for accuracy, control sheets for chance.
3. FPR discipline unchanged: a control sheet crossing the accusation
   threshold anywhere fails the campaign report.

## Budget guardrails

Everything above is $0 on free tiers. Watch two dials in Supabase:
Storage (past ~1 GB of uploads, take one month of Pro at $25 or ask
volunteers to skip uploading full-size originals) and Auth email rate
(if magic-link sign-ins spike, plug a free Resend/Brevo SMTP into Auth
settings). Optional ~$12: a memorable domain pointed at the Netlify site.
