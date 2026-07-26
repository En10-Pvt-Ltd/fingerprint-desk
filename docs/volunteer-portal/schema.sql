-- Volunteer wild-corpus portal: Supabase schema.
-- Run this once in the Supabase SQL editor of a fresh free-tier project.
-- Companion frontend: demo/volunteer.html + demo/volunteer.js (paste the
-- project URL + anon key there). Also create a PRIVATE storage bucket
-- named "captures" (Storage > New bucket > name: captures, public: OFF).

-- ---------------------------------------------------------------- packs
-- One row per pre-generated print pack (app/tools/make_volunteer_packs.py).
-- url is relative to the demo site origin (e.g. packs/pack_FP001.zip).
create table if not exists public.packs (
  pack_id    text primary key,
  url        text not null,
  claimed_by uuid references auth.users (id),
  claimed_at timestamptz
);

-- ------------------------------------------------------------- captures
create table if not exists public.captures (
  id            uuid primary key default gen_random_uuid(),
  volunteer     uuid not null references auth.users (id),
  pack_id       text not null references public.packs (pack_id),
  sheet         text not null check (sheet in ('A', 'B', 'C')),
  phone_tier    text not null check (phone_tier in
                    ('budget', 'mid', 'flagship')),
  angle         int  not null check (angle in (0, 15, 30, 45)),
  lighting      text not null check (lighting in
                    ('office', 'dim_tube', 'flash_glare',
                     'window_backlight')),
  framing       text not null check (framing in
                    ('full', 'half', 'single-question',
                     'single-paragraph')),
  messaging     text not null check (messaging in
                    ('none', 'wa', 'wa_x2', 'tg', 'wa_then_tg')),
  original_path text,
  messaged_path text,
  note          text,
  consent       boolean not null check (consent),
  created_at    timestamptz not null default now()
);

-- ----------------------------------------------------- claim_pack() RPC
-- Atomically assigns one unclaimed pack per volunteer (idempotent: a
-- volunteer who already holds a pack gets the same one back).
create or replace function public.claim_pack()
returns public.packs
language plpgsql security definer set search_path = public as $$
declare p public.packs;
begin
  select * into p from packs where claimed_by = auth.uid() limit 1;
  if found then return p; end if;
  update packs set claimed_by = auth.uid(), claimed_at = now()
   where pack_id = (select pack_id from packs
                     where claimed_by is null
                     order by pack_id limit 1
                     for update skip locked)
  returning * into p;
  return p;   -- null when no packs remain
end $$;

-- -------------------------------------------------- row-level security
alter table public.packs    enable row level security;
alter table public.captures enable row level security;

-- volunteers see only their own pack row (claiming goes through the RPC)
create policy packs_select_own on public.packs
  for select using (claimed_by = auth.uid());

-- volunteers insert and read only their own captures; no update/delete
-- (submissions are evidence — corrections go through the maintainer)
create policy captures_insert_own on public.captures
  for insert with check (volunteer = auth.uid());
create policy captures_select_own on public.captures
  for select using (volunteer = auth.uid());

-- --------------------------------------------------- storage policies
-- Bucket "captures" (private). Volunteers may upload only under their own
-- user-id prefix and read back their own files. The maintainer pulls the
-- full bucket with the service-role key for offline scoring.
create policy captures_upload_own on storage.objects
  for insert with check (
    bucket_id = 'captures'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
create policy captures_read_own on storage.objects
  for select using (
    bucket_id = 'captures'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- ------------------------------------------------------- pack import
-- After running make_volunteer_packs.py, load demo/packs/index.json into
-- the packs table. Easiest one-liner (psql or SQL editor), adjust values:
--   insert into public.packs (pack_id, url) values
--     ('FP001', 'packs/pack_FP001.zip'),
--     ('FP002', 'packs/pack_FP002.zip')
--   on conflict (pack_id) do nothing;
-- (Or paste the JSON through a spreadsheet -> insert statement.)

-- --------------------------------------------------------- ops notes
-- * Auth > Providers: enable Email (magic link / OTP). Supabase's
--   built-in mailer is rate-limited (~4/hour per address) but fine for a
--   small campaign; move Auth SMTP to a free Resend/Brevo account if
--   sign-ins spike.
-- * Free tier: 500 MB database, 1 GB storage, 50k monthly active users.
--   WhatsApp-output images are ~0.2-0.5 MB; originals 2-5 MB. If storage
--   nears 1 GB, either ask volunteers to upload originals only for a
--   subset of cells, or take one month of Pro ($25) during the campaign.
-- * Export for scoring:
--     supabase storage cp -r ss:///captures ./wild_corpus --experimental
--   then join with a CSV export of the captures table; score offline
--   against appdata/volunteer_packs/<pack_id>/private/ ground truth.
