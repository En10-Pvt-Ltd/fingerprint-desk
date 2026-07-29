# Security Policy

## Reporting a vulnerability

**Please report security issues privately. Do not open a public issue.**

**Primary channel — GitHub Private Vulnerability Reporting.** Use the repository's
**Security → Report a vulnerability** button (GitHub → *Security* tab → *Report a
vulnerability*). This opens a private advisory visible only to the maintainer, keeps the
discussion attached to the code, and turns into a published advisory + CVE if warranted.
For a solo-maintained project this is the reliable channel: there is no separate inbox to
miss.

> **Maintainer setup (one-time):** enable it under *Settings → Code security and analysis →
> Private vulnerability reporting*.

**Fallback — email.** If you cannot use GitHub, email `info@en10.in`.

Please include enough to reproduce: affected version/commit, steps, and impact. If you
have a proof of concept, attach it or link it privately.

We aim to acknowledge a report within **7 days** and to agree a disclosure timeline with
you. We will credit reporters who want credit.

## What is in scope

- The web application (`app/`): authentication, CSRF, per-user ownership and file gating,
  the no-account volunteer pack flow, upload handling, and untrusted-PDF parsing.
- The isolation boundary for untrusted PDFs (the subprocess worker).
- Anything that could leak ground truth (per-copy metadata, seeds, pack mappings) to a
  party who should not have it.

## The attribution logic is security-critical — but report it here, not in public

A way to make the tool **falsely attribute an unmarked control copy** is, for this project,
both a correctness bug and a security issue: it manufactures false evidence against a
person. Report it privately through this policy first. We treat it as release-blocking.

Conversely, a technique that lets a leaker **strip or defeat** the fingerprint is expected
and largely documented (retyping defeats it; see the threat model). Novel, low-effort
removal attacks that a normal recipient could perform are still worth reporting.

## Out of scope

- Denial of service from a single client on a self-hosted instance beyond the built-in
  per-client rate limits (operators are expected to run behind the bundled reverse proxy).
- Findings that require a malicious administrator of the deploying institution.
- The synthetic channel simulator producing unrealistic numbers (it is a dev aid, never a
  reported result).

## Deployment hardening reminders

- Set a strong `SECRET_KEY`; never ship the dev sign-in shim (`FF_DEV_LOGIN`) in production.
- Keep the app port unpublished and terminate TLS at the bundled proxy; set
  `FF_TRUST_PROXY=1` so rate limits key on the real client IP.
- Back up `/data` (SQLite + sealed commitments) — it holds all tracing ability. Losing that
  data directory means a document can never be traced.
