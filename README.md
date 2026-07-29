# Fingerprint Desk

[![CI](https://github.com/En10-Pvt-Ltd/fingerprint-desk/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/En10-Pvt-Ltd/fingerprint-desk/actions/workflows/ci.yml) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21588529.svg)](https://doi.org/10.5281/zenodo.21588529)

**Trace a leaked document photo back to the exact copy it came from.**

Every printed copy carries the same visible text but a different invisible pattern of
sub-millimetre shifts in word and line spacing. A photograph of a leaked page, taken on a
phone and pushed through WhatsApp, can be decoded blind to identify which copy leaked,
with a stated probability of false accusation.

Built for examination papers, and useful for any confidential document distributed to
named recipients: legal discovery, board papers, pre-publication manuscripts, internal
memos.

```
Upload a document  ->  Generate N named copies  ->  Print and distribute
                                                          |
        Which copy leaked?  <-  Decode  <-  Someone photographs a page
```

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

## Validation status

Be skeptical of any watermarking project that will not tell you this table.

| Carrier | What it handles | Real print -> photo -> messaging tested? |
|---|---|---|
| Rendered (line + word shift) | pasted text, extracted PDF text | Yes, limited: 14/15 bits recovered on a real capture |
| Preserved (text PDFs) | text PDFs, layout kept | Not yet, simulated channel only |
| Raster (scanned PDFs) | image-only PDFs | Not yet, simulated channel only |
| Vector (outline-text PDFs) | glyphs as paths | Not yet, simulated channel only |

**The simulated channel is never reported as a result.** A corpus campaign collecting real
print-photograph-messaging captures across many printers and phones is in progress. Results
will be published here with the raw corpus.

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

**Directly, without Docker (local mode — no accounts at all):**

```bash
pip install -r requirements.txt -r app/requirements.txt
python app/serve.py         # -> http://localhost:8765
```

With `FF_MODE` unset and the default loopback bind, the app runs in **local mode**: no
sign-in, you are the single operator (with admin rights). Local mode refuses to serve on
anything but loopback — to put the app on a network, set `FF_MODE=server` (Docker above
does this for you).

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
per-copy ground truth and the sealed commitments. It is not exported to you as a key — it
lives on disk. **If that directory is lost (reinstall, disk failure, deleting the folder),
every document that instance has generated becomes permanently untraceable.** Backing it up
is the operator's responsibility. The directory is:

- **Docker:** the `data/` folder next to `docker-compose.yml` (data under `data/appdata/`).
- **Direct run (`python app/serve.py`):** the `appdata/` folder in the project directory.

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
