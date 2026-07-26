#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Independently audit a built public export BEFORE it is pushed. Makes no
# assumption that the export is clean because the source tree is clean:
# it re-scans the export's own tree and its (single-commit) history for
# secrets, stray runtime data, database/journal files, .git leftovers,
# and .env files, then prints the full file manifest to eyeball.
#
# Usage: scripts/scan-export.sh <EXPORT_DIR>
set -uo pipefail

DEST="${1:?usage: scan-export.sh <EXPORT_DIR>}"
[ -d "$DEST/.git" ] || { echo "!! $DEST is not a git repo" >&2; exit 1; }
fail=0
note() { printf '\n=== %s ===\n' "$1"; }

# Benign patterns excluded: env/rand key HANDLING (not literal values), doc
# prose, and this scanner's own regex source. A literal assigned value is
# what matters — section 1b greps for exactly that.
BENIGN="SECRET_KEY not set|SECRET_KEY =|secret_key=SECRET_KEY|os\.environ|getenv|token_hex|password-protected|no password|SECRET-CONTACT|CONDUCT-CONTACT|openssl rand|database password|magic-link|# .*password|example\.org|xxx'"
note "1. secret-like strings in TRACKED files (tree)"
if git -C "$DEST" grep -nI -E "(api[_-]?key|secret[_-]?key|password|passwd|-----BEGIN|xox[baprs]-|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,})" \
      -- . ':(exclude).agents/*' ':(exclude)scripts/scan-export.sh' 2>/dev/null \
      | grep -vE "$BENIGN"; then
  echo "!! review the hits above"; fail=1
else echo "clean (no live-looking secrets)"; fi

note "1b. LITERAL assigned secret values (the real leak signal)"
if git -C "$DEST" grep -nIE "(secret|password|token|api_key)[a-z_]*\s*[:=]\s*['\"][A-Za-z0-9/+]{12,}" \
      -- . ':(exclude)scripts/scan-export.sh' 2>/dev/null; then
  echo "!! a literal secret value is assigned above"; fail=1
else echo "clean (no literal secret values assigned)"; fi

note "2. real email / PII in tracked files"
if git -C "$DEST" grep -nI -E "[A-Za-z0-9._%+-]+@(gmail|yahoo|outlook|hotmail)\.com|@[a-z]+\.(edu|ac\.in)" -- . 2>/dev/null \
      | grep -vE "example\.(org|com)|users\.noreply\.github\.com"; then
  echo "!! real personal email(s) above — genericise before pushing"; fail=1
else echo "clean (only example/noreply addresses)"; fi

note "3. git HISTORY blobs for the same secrets (not just the tree)"
if git -C "$DEST" log --all -p -- . ':(exclude)scripts/scan-export.sh' \
      | grep -iE "(secret[_-]?key *=|password *=|-----BEGIN|@gmail\.com|xox[baprs]-|AKIA[0-9A-Z]{16})" \
      | grep -vE "SECRET_KEY *=$|SECRET_KEY =|SECRET_KEY not set|secret_key=SECRET_KEY|os\.environ|token_hex|example\.org|noreply|openssl|create role|magic-link"; then
  echo "!! history contains the above — a squash export should NOT"; fail=1
else echo "clean (single squashed commit carries no stray secrets)"; fi

note "4. database / WAL / journal / .env files tracked"
if git -C "$DEST" ls-files | grep -iE "\.(db|db-wal|db-shm|sqlite|sqlite3)$|-journal$|(^|/)\.env$"; then
  echo "!! runtime DB/journal/.env above should not ship"; fail=1
else echo "clean (no db/journal/.env tracked)"; fi

note "5. nested .git leftovers or submodules"
nested=$(find "$DEST" -mindepth 2 -name .git -print 2>/dev/null)
if [ -n "$nested" ] || [ -f "$DEST/.gitmodules" ]; then
  echo "!! nested .git or submodule:"; echo "$nested"; ls "$DEST/.gitmodules" 2>/dev/null; fail=1
else echo "clean (only the top-level .git)"; fi

note "6. tracked appdata/ content (eyeball: is any of this private/runtime?)"
appd=$(git -C "$DEST" ls-files | grep -E "^appdata/" | sed -E 's#(appdata/[^/]+(/[^/]+)?)/.*#\1/...#' | sort -u)
if [ -n "$appd" ]; then echo "$appd"; echo "-- confirm each is a synthetic fixture, not real captures / ground truth"; else echo "no appdata/ tracked"; fi

note "7. FULL FILE MANIFEST ($(git -C "$DEST" ls-files | wc -l | tr -d ' ') files)"
git -C "$DEST" ls-files

note "RESULT"
[ "$fail" -eq 0 ] && echo "PASS — no blocking findings (still eyeball the manifest + appdata above)" \
                   || echo "REVIEW NEEDED — see !! lines above"
exit 0
