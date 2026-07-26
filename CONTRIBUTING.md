# Contributing to Fingerprint Desk

Thank you for helping. This is a forensic tool, so the bar for changes that touch the
attribution path is high; everything else is the usual friendly open-source flow.

## The one rule that overrides preference

**Anything that weakens the false-accusation discipline is rejected on principle, not on
taste.** The tool must never accuse an innocent copy. Concretely, a change will not be
merged if it:

- lowers the attribution gates (Bonferroni-corrected binomial p ≤ 1e-3, a minimum symbol
  count, and a margin over the runner-up) without a rigorous justification and new tests,
- makes an unmarked **control** copy attributable under any preset, or
- reports a **simulated-channel** number as if it were a real-capture result.

The strongest contribution you can make is the opposite: a reproducible case where a
control *is* falsely attributed. That is a release-blocking bug, and we want it.

## The highest-value contribution needs no code

Real **print → photograph → messaging** captures across different printers and phones are
what the project actually needs. See `docs/contribute-captures.md`. No pull request
required.

## Development setup

Requirements are in `requirements.txt` and `app/requirements.txt`
(`numpy`, `Pillow`, `opencv-python`, `PyMuPDF`/`fitz`, `pikepdf`, `fastapi`, ...).

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r app/requirements.txt
```

**Font note (required):** the encoder needs a **serif** TrueType font, and the default
path is Linux-only (the container reference `DejaVuSerif.ttf`). On other platforms point
to a serif face:

```bash
export FF_FONT_PATH=/path/to/DejaVuSerif.ttf     # macOS/Linux
$env:FF_FONT_PATH = "C:\Windows\Fonts\times.ttf" # Windows PowerShell
```

## Running the tests

The end-to-end self-test drives the live API in-process (no server needed) against a
throwaway data dir, and is the gate every change must pass:

```bash
FF_FONT_PATH=/path/to/serif.ttf python app/selftest.py     # expects "ALL N CHECKS PASSED"
python metrics.py                                          # reproduces the spec's tier cells
```

**CI on Linux is authoritative.** The suite passing locally on Windows or macOS is
necessary but not sufficient. Some protections — notably the PDF worker's `RLIMIT_AS`
memory ceiling — are enforced only on Linux (Python's `resource` module does not exist on
Windows, so `setrlimit` is silently skipped). A change can therefore be green locally and
red on the Linux CI runner. Trust the GitHub Actions result; when in doubt, reproduce in a
Linux container (`docker run … python:3.11-slim`).

CI (`.github/workflows/ci.yml`) runs the metrics self-tests, the app self-test, the
demo-site verification, and the submission-scoring self-test on every push and PR.

## Pull request flow

1. Branch off `main`.
2. Keep the change focused; match the surrounding code's style (plain-stdlib Python, plain
   ES for the frontend — no frameworks, no build step).
3. Add or update self-test coverage for anything touching encode/decode/attribution.
4. Run `python app/selftest.py` locally and make sure it is green.
5. Open the PR. CI must pass. `main` is protected.

## Reporting bugs and asking for features

Use the issue templates. For a **suspected false attribution**, use the dedicated template
and include the capture (or a way to reproduce it) — that class of report is treated as
highest priority.

## Security

Do not open public issues for vulnerabilities, especially in the attribution logic. See
[SECURITY.md](SECURITY.md).

## Maintainer & governance

This is a young project with a single maintainer (benevolent-dictator model). Decisions,
especially on the attribution path, rest with the maintainer and are guided by the rule at
the top of this file. The aim is to respond to issues and PRs within about a week; silence
is not a decision, so ping if something stalls.

## Licensing of contributions

By submitting a contribution you agree it is licensed under the project's
[Apache License 2.0](LICENSE), including its patent grant.
