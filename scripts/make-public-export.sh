#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Build a CLEAN public export of this repo as a brand-new git repository
# with a single initial commit and NO prior history.
#
# Why squash rather than filter-repo: the private history has no external
# contributors to credit, so it carries no public value, and a fresh
# snapshot cannot miss a sensitive blob we failed to think of — it only
# ever contains the tracked files at HEAD, nothing else.
#
# This script NEVER touches the private repo or its .git. It only reads
# HEAD (via `git archive`, which emits tracked files only — no .git, no
# untracked, no gitignored appdata) and writes a new directory elsewhere.
# It does NOT push anywhere.
#
# Usage:
#   scripts/make-public-export.sh [EXPORT_DIR]
# Default EXPORT_DIR: ../fingerprint-desk-public
set -euo pipefail

# ---- config ------------------------------------------------------------------
# GitHub no-reply so future public commits never re-add a real email.
# Replace with your ID-prefixed form from https://github.com/settings/emails
# (e.g. 12345678+nirajkasar@users.noreply.github.com) for exact matching.
NOREPLY_EMAIL="${FF_EXPORT_EMAIL:-nirajkasar@users.noreply.github.com}"
NOREPLY_NAME="${FF_EXPORT_NAME:-Niraj Kasar}"

SRC="$(git rev-parse --show-toplevel)"
DEST="${1:-$(dirname "$SRC")/fingerprint-desk-public}"
REV="$(git rev-parse --short HEAD)"

echo ">> source repo : $SRC (HEAD $REV)"
echo ">> export dir  : $DEST"
echo ">> commit ident: $NOREPLY_NAME <$NOREPLY_EMAIL>"

if [ -e "$DEST" ]; then
  echo "!! $DEST already exists — refusing to overwrite. Remove it or pass a new path." >&2
  exit 1
fi

# ---- 1. snapshot tracked files at HEAD (no .git, no untracked, no ignored) ----
mkdir -p "$DEST"
git archive --format=tar HEAD | ( cd "$DEST" && tar -xf - )

# ---- 2. init a fresh repo with a single commit -------------------------------
git -C "$DEST" init -q -b main
git -C "$DEST" config user.email "$NOREPLY_EMAIL"
git -C "$DEST" config user.name  "$NOREPLY_NAME"
git -C "$DEST" add -A
git -C "$DEST" -c commit.gpgsign=false commit -q \
  -m "Initial public release: Fingerprint Desk

Forensic document fingerprinting: invisible per-copy geometry codes,
blind phone-photo decode, and a false-accusation-bounded attribution
rule. Squashed snapshot of the private development archive."

echo ">> export built: single commit $(git -C "$DEST" rev-parse --short HEAD) on 'main'"
echo ">> NOTE: not pushed anywhere. Review the scan + manifest before pushing."
