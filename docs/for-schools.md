# For schools and exam offices — a no-terminal guide

You do not need to be technical to *use* this, but someone does need to **run an instance for
you** first — either a hosted web address your IT set up, or the Docker deployment in the
main README. This guide assumes you have an address to open and can sign in.

## Read this first: keep the key and the receipt safe

Everything needed to trace a leak — the invisible pattern in each copy and the sealed record
that proves it — lives in **one data directory on the machine running the app**. If that
directory is lost (the machine is reinstalled, its disk fails, the folder is deleted) **and
no recovery key was exported**, then every document that instance generated becomes
**permanently untraceable**.

You are not helpless against that. For each campaign, whoever runs the app can export two
things from the campaign's own page — ask them to:

- **A recovery key**, kept somewhere *other than that machine* (a backup drive, your
  institution's secure store). It can trace that campaign's leaks — and name who received the
  leaked copy — from a fresh install, even if the original machine is gone. It does not
  contain the document, but it does contain the record of who got which copy, so keep it
  safe. It can be locked with a passphrase, and **a forgotten passphrase cannot be
  recovered**, so store the passphrase separately from the file.
- **A commitment receipt** — a short text file with no sensitive contents — **deposited with
  someone outside (your counsel, or a dated email to yourself) *before* the copies go out.**
  Dated before any leak, it is what lets an outside party check an accusation instead of
  taking your word for it. It survives even a forgotten passphrase.

Backing up the data directory is still the **operator's** responsibility — make sure someone
owns that job — but the recovery key is your safety net if it fails. The directory is:

- **Docker deployment:** the `data/` folder next to `docker-compose.yml` (all tracing data
  lives under `data/appdata/`).
- **Direct run (`python app/serve.py`):** the `appdata/` folder inside the project directory.

Also keep the **unmarked control copy** the tool makes automatically — an untagged copy you
use to sanity-check any future accusation.

## Step 1 — Sign in

Open the web address and sign in with the account your IT set up for you (email and
password). Then click **Start a test**.

## Step 2 — Create the copies

- Paste the document text, or upload a PDF. The tool previews how many pages it will produce
  and whether each page can carry a strong hidden mark.
- Choose how many copies to make. **The point-and-click app currently makes 2 to 5 copies at
  a time**, each auto-named *Variant 1, Variant 2, …*, plus **one unmarked control**
  automatically.
- Press **Create the marked copies**.

> Larger named campaigns — one copy per centre or per student, with your own naming such as
> `Centre-1 … Centre-40` — are **planned but not yet available** in the app. Today they
> require the command-line tool; ask your operator.

## Step 3 — Download, print, distribute

- Download each copy's PDF from the test page. (A single **download-all-as-a-ZIP** button is
  **planned but not yet available** — for now, download the copies one at a time.)
- **Print at 100% / actual size** (not "fit to page"), on plain white paper. **Do not
  photocopy** the copies — photocopying can blur the mark. Hand each recipient their own copy
  and record who received which.

## Step 4 — Investigate a leak

If a page leaks (for example, someone shares a phone photo), open that same test on the same
instance and **upload the photo**. You get a plain-language verdict, never a raw number:

> **We read this as Variant 14** — with a plain statement of how confident the reading is.

or, shown with equal weight:

> **No attribution.** The photo does not carry enough recoverable signal to name a source.
> This is normal for small crops or heavily degraded images. It does **not** mean the
> document was untagged.

**Before you act on any positive result,** photograph and check your **control copy** the
same way. If the control is ever attributed, do not rely on the result — stop and report it
as a bug.

## What you can ignore

Anything about bits, corrected p-values, deskew, or the decoding pipeline lives behind a
**"Technical details"** toggle for a forensic analyst. You never need it for normal use.

## Responsible use

Where the law or basic fairness requires it, tell recipients their copies are individually
traceable. Deterrence only works when people know it exists — and disclosure is often a
legal obligation.
