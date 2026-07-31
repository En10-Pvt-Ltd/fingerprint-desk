# Fingerprint Desk

[![CI](https://github.com/En10-Pvt-Ltd/fingerprint-desk/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/En10-Pvt-Ltd/fingerprint-desk/actions/workflows/ci.yml) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21588529.svg)](https://doi.org/10.5281/zenodo.21588529)

**Trace a leaked document photo back to the exact copy it came from.**

Every printed copy carries the same visible text but a different invisible pattern of
sub-millimetre shifts in word and line spacing. A photograph of a leaked page, taken on a
phone and pushed through WhatsApp, can be decoded blind to identify which copy leaked,
with a stated probability of false accusation.

Built for examination papers and documents like them. The mark lives in line and word
spacing, so it needs **long, continuous, plain body text** — it is not a universal document
tagger. Read [What documents work](#what-documents-work) **before** you prepare a print run.

```
Upload a document  ->  Generate N named copies  ->  Print and distribute
                                                          |
        Which copy leaked?  <-  Decode  <-  Someone photographs a page
```

---

## What documents work

The fingerprint is carried in the spacing **between lines of text**, so a document must have
enough regular body-text lines, over enough pages, to hold it. This is a real limit of the
method — check it before committing a print run, not after:

**Works** — long, continuous, plain body text:
- examination papers, reports, contracts, pre-publication manuscripts, and other multi-page
  documents that are mostly paragraphs of ordinary body text.

**Does not work** — too few lines, or a layout the decoder cannot read:
- forms, invoices, statements, receipts, certificates;
- CVs/résumés, brochures, flyers, invitations, posters, slide decks;
- anything graphics-heavy or multi-column;
- scanned images with no text layer, and password-protected PDFs.

Rule of thumb: **mostly paragraphs over several pages → works; mostly a layout (fields,
tables, headings, graphics) or only a page or two → does not.**

You do not have to judge this by eye. When you generate the copies, the app decodes each
copy's own clean render and **refuses to create the campaign** if the marks do not read
back — telling you which problem it is (*wrong document type* → use plain body text;
*too little text* → use a longer document). The list above is so you choose well **before**
printing; the guard is the guarantee that a bad choice can never reach distribution.
The tested evidence behind this guidance — one representative document per claimed use
case, plus a 14-document everyday-PDF sample — is recorded in
[docs/document-envelope.md](docs/document-envelope.md).

---

## What makes this different

Most document watermarking is either visible (and therefore croppable), digital-only (and
therefore destroyed by printing), or offers a bare match/no-match with no error rate.

- **Reads from an ordinary phone photo.** No scanner, no UV light, no special ink.
- **Built for the real channel.** Print, phone photograph, WhatsApp recompression. What has
  actually been confirmed on real captures, and what has not, is in Validation status below.
- **Ships a false-accusation bound, not a guess.** Attribution requires a Bonferroni
  corrected binomial p-value at or below 1e-3, a minimum symbol count, and a margin over
  the runner-up. Otherwise the answer is an honest "no attribution", which is treated as a
  correct result, not a failure.
- **Verifiable accusations.** Ground truth is sealed in a SHA-256 commitment before
  distribution, so an accusation can be checked by a third party instead of trusted.
- **Preserves your document.** For scanned and vector PDFs, everything outside a shifted
  line stays pixel-identical or byte-exact. Tables, stamps, figures and letterheads survive.

## What it does NOT do

Stated plainly, because a forensic tool that oversells itself is worse than useless.

- **It does not prevent leaks.** It traces them, and it deters.
- **Retyping defeats it.** Anyone who retypes or AI-transcribes the paper carries no mark.
  See [docs/threat-model.md](docs/threat-model.md).
- **Leaks before differentiation are invisible.** If a document leaks before per-copy
  copies exist, there is nothing to trace.
- **Small fragments are leads, not proof.** A single cropped question can point at a
  source but cannot untangle a colluding group.
- **Some documents can't carry the mark** — heavy graphics, large headings, columns, or
  very little text. You don't have to guess which: the app **verifies your specific
  document when it makes the copies and refuses** (with the reason and a fix) if the marks
  don't read back. See [Every campaign is self-verified](#every-campaign-is-self-verified).

## Validation status

Be skeptical of any watermarking project that will not tell you this table.

| Carrier | What it handles | Real print -> photo -> messaging tested? |
|---|---|---|
| Rendered (line + word shift) | pasted text, extracted PDF text | Yes, limited: 14/15 bits recovered on a real capture |
| Preserved (text PDFs) | text PDFs, layout kept | Limited: one real capture (`field-test-002/`) — 1 of 2 document classes passed (`times11` aggregate 37/41 = 0.902, page-1 14/14 and 13/14); the 10 pt heading-heavy class did not, and is recorded as such — plus simulated channel |
| Raster (scanned PDFs) | image-only PDFs | Not yet, simulated channel only |
| Vector (outline-text PDFs) | glyphs as paths | Not yet, simulated channel only |

**The simulated channel is never reported as a result.** A corpus campaign collecting real
print-photograph-messaging captures across many printers and phones is in progress. Results
will be published here with the raw corpus.

## Every campaign is self-verified

[What documents work](#what-documents-work) (above) is guidance for choosing before a print
run. This is the **guarantee** behind it: when the app makes the copies it decodes each
copy's *own clean render* through the **same decoder a real investigation uses**, and
**refuses to create the campaign** (fail closed, no override) if the true copy does not read
back clearly. It names which of the two problems it is, because the fixes differ:

- *marks don't read back on this document type* (graphics, headings, columns) → use a
  document that is mostly continuous body text;
- *too few readable marks* (the document is too short) → use a longer document, or more pages.

So a document that could never be traced can never reach distribution — the "hope you picked
a good document" caveat is now checked and enforced, not left to the reader.

## Quick start

**With Docker (server mode — accounts and invites):**

```bash
git clone https://github.com/En10-Pvt-Ltd/fingerprint-desk
cd fingerprint-desk
cp .env.example .env        # then set SECRET_KEY:  openssl rand -hex 32
docker compose up -d
```

Open **http://localhost** — the bundled Caddy reverse proxy serves the app. The first
visit shows a **one-time setup screen**: create the administrator account (email +
password). After that, sign in with it, click **Start a test**, press **No PDF handy? Use
our sample text**, then **Create the marked copies**. Contributors get accounts via
single-use invite links minted on the `/admin` page. The `.env.example` defaults
(`DOMAIN=localhost`, `BASE_URL=http://localhost`) are for evaluating on your own machine.

**Directly, without Docker (local mode — no accounts at all):** requires **Python 3.11 or
newer**.

```bash
pip install -r requirements.txt -r app/requirements.txt
python app/serve.py         # -> http://localhost:8765
```

On Windows you can instead **double-click `Start Fingerprint Desk.bat`** — it checks for
Python 3.11+ (and links the installer if it is missing), installs dependencies on first
run, starts the app in local mode, and opens it in your browser.

With `FF_MODE` unset and the default loopback bind, the app runs in **local mode**: no
sign-in, you are the single operator (with admin rights). Local mode refuses to serve on
anything but loopback — to put the app on a network, set `FF_MODE=server` (Docker above
does this for you). Rendering uses the bundled Liberation Serif font, so no font setup is
needed on any OS.

### See a real decode in two minutes (no printer)

You don't need to print anything to watch the decoder work. The repo ships a real phone
photo of a marked page; decode it inside the running container:

```bash
docker compose exec app python robust_decode/run_robust.py --img received.jpeg --meta meta.json
```

It reports the recovered line-shift bit accuracy from that real capture (about 14/15) and
prints a GO / NO-GO line — proof the pipeline reads a genuine phone photo end to end.

### Deploying publicly

Set `DOMAIN` and `BASE_URL` in `.env` to your real domain (Caddy gets HTTPS
automatically); Docker deployments always run in server mode. Do the first-run setup
immediately after the app comes up — until the admin account exists, anyone who reaches
the URL could claim it. Accounts are invite-only after that. Upgrading from a version that
used Google sign-in? See [MIGRATION.md](MIGRATION.md).

### Backing up (do not skip)

All tracing ability lives in **one data directory** on the machine running the app: the
per-copy ground truth and the sealed commitments. **If that directory is lost (reinstall,
disk failure, deleting the folder) and you never exported a recovery key, every document
that instance has generated becomes permanently untraceable.** Back it up. The directory is:

- **Docker:** the `data/` folder next to `docker-compose.yml` (data under `data/appdata/`).
- **Direct run (`python app/serve.py`):** the `appdata/` folder in the project directory.

**Two exports make a campaign survivable off this machine** (from a campaign's own page):

- The **recovery key** (`<campaign>.fdkey.json`) is a portable backup of one campaign's
  ground truth. Stored **off this machine**, it lets you trace that campaign's leaks — and
  name who received the leaked copy — from another install, even if this data directory is
  gone. It never contains the document itself, but it does hold the recipient mapping, so
  keep it safe; encrypt it with a passphrase (there is **no recovery if you forget the
  passphrase** — store it separately). See
  [docs/recovery-key-format.md](docs/recovery-key-format.md).
- The **commitment receipt** is a few lines holding only the digests and seal — no ground
  truth. **Deposit it with a third party before you distribute copies**: dated before any
  leak, it is what lets an accusation be checked without trusting this machine. It survives
  even a forgotten passphrase.

Not a developer? See [docs/for-schools.md](docs/for-schools.md) for a no-terminal guide.

## How it works

1. **Encode.** Lines are grouped in triplets; the middle line's baseline is shifted by
   about 2 px at 300 dpi. Alternating interior word gaps are widened or narrowed by about
   3 px. Neither is visible to a reader. Each copy gets a different pattern.
2. **Commit.** A SHA-256 commitment over the ground truth and the emitted files is sealed
   before anything is distributed, so the mapping cannot be altered after a leak appears.
3. **Decode.** A leaked image is deskewed, lines are segmented, baselines and word gaps are
   measured, and only the *sign* of each differential is read, which makes decoding
   scale-free across capture resolutions. No original document and no fiducial markers are
   needed.
4. **Attribute, or refuse to.** The best-matching copy is accused only if it clears all
   three gates. Otherwise the tool reports no attribution.

Full method and the statistical guarantees: [docs/method.md](docs/method.md). The cheap
single-carrier smoke test that started the project: [docs/smoke-test.md](docs/smoke-test.md).

## Responsible use

This is a forensic tool that produces evidence used to accuse people. Three requests:

- **Never accuse on a single weak reading.** Use the tiered verdict the tool gives you.
- **Always run an unmarked control copy** through the same pipeline. If the control ever
  produces an attribution, stop and open an issue, that is a bug and we treat it as
  release-blocking.
- **Tell people their documents are fingerprinted** where the law or basic decency
  requires it. Traceability is a deterrent, and deterrence only works if it is known.

Security issues: see [SECURITY.md](SECURITY.md). Please do not open public issues for
vulnerabilities in the attribution logic.

## Contributing

New contributors are genuinely welcome, especially:

- **Real captures for the corpus.** The highest-value contribution. No coding needed.
  See [docs/contribute-captures.md](docs/contribute-captures.md).
- **Non-Latin script carriers.** Devanagari, Arabic, Amharic, Ethiopic. Open problem.
- **Independent verification.** Try to make the tool falsely accuse a control copy. If you
  succeed, that is the most useful bug report this project can receive.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Citation

If you use this in research:

```bibtex
@software{fingerprint_desk,
  title     = {Fingerprint Desk: Forensic fingerprinting for printed documents},
  author    = {Kasar, Niraj Vijay},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.21588529},
  url       = {https://doi.org/10.5281/zenodo.21588529}
}
```

## License

Apache License 2.0. See [LICENSE](LICENSE).

Apache 2.0 was chosen deliberately over MIT: it carries an explicit patent grant, so
adopters are protected from patent claims by contributors, including the maintainers.
