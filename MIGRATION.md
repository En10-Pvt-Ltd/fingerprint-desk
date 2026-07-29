# Migrating to the FF_MODE auth redesign

This release replaces Google sign-in with two explicit deployment modes and makes
`ADMIN_EMAILS` a bootstrap seed instead of a live admin check. Existing data is preserved;
the schema changes are purely additive.

## What changed

- **`FF_MODE` is required for network deployments.** `FF_MODE=server` gives email+password
  accounts (Argon2id): the first visit runs a one-time setup that creates the admin, and
  further accounts are minted as single-use, expiring invite links from `/admin`.
  `FF_MODE=local` is a single-operator run with no accounts at all and **refuses to bind to
  anything but loopback** (the bound sockets are verified after bind; any ambiguity is
  fatal). If `FF_MODE` is unset, the app starts only for an unambiguously local
  configuration (loopback `HOST`, non-https `BASE_URL`) — anything else exits with an error
  instead of silently exposing or silently breaking. `docker-compose.yml` pins
  `FF_MODE=server`.
- **`ADMIN_EMAILS` is now seed-only.** Admin status lives solely in the database
  (`users.is_admin`). At startup, every *existing* user whose email is listed in
  `ADMIN_EMAILS` gets the persistent admin flag — so on upgrade, active admins keep admin.
  While no admin exists at all, a signing-in listed user becomes the first admin. Once any
  admin exists, `ADMIN_EMAILS` never elevates anyone again; promote further admins
  deliberately (e.g. `UPDATE users SET is_admin=1 WHERE email='...'` on `app.db`).
- **Google sign-in (and the `FF_DEV_LOGIN` shim) are removed.** `authlib` is no longer a
  dependency and `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are ignored. A hosted mode with
  OAuth is a possible later phase. Existing Google-account rows are kept (tests, scans and
  feedback stay attributed to them), but they have no password, so they cannot sign in
  until given one. There is no password-reset flow yet: to hand an existing account a
  password, set `users.password_hash` to an Argon2id hash directly, e.g.
  `python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('NEW-PASSWORD'))"`
  and write the result into that user's row. Alternatively, invite the person to a fresh
  account (their old contributions stay under the old row).

## Schema

Additive only: `users.password_hash`, `users.auth_kind`, and a new `invites` table. The
`google_sub` column is kept and repurposed as a generic auth subject (`local:<email>` for
password accounts, `implicit` for the local-mode operator). No data is dropped or
rewritten.

## Rollback

Redeploy the prior version. Old code ignores the new columns and the `invites` table, and
it already honors `users.is_admin` — so admins seeded by this version keep admin after a
rollback. Accounts created as local password accounts will not be able to sign in under
the old (Google-only) code.
