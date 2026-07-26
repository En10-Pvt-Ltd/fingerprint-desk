#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pre-generate volunteer print packs for the wild-corpus campaign.

    python app/tools/make_volunteer_packs.py --n 25 \
        --out appdata/volunteer_packs --packs-dir demo/packs

Each pack contains three print-ready A4 sheets (two uniquely-seeded marked
variants + one unmarked control, shuffled to anonymous names A/B/C) built
by the repo's own encoder — never copyrighted exam papers. The PUBLIC zip
(dropped into demo/packs/ for static hosting) carries only the sheets and
instructions; ground truth (metas + role mapping + sha256 manifest) stays
PRIVATE under appdata/volunteer_packs/<pack_id>/private/ and scoring
happens offline in this repo.

Packs are generated offline precisely so the volunteer portal needs zero
server compute: static hosting + Supabase free tier carry everything.
"""
import argparse
import hashlib
import shutil
import json
import os
import random
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
REPO = os.path.dirname(APP)

INSTRUCTIONS = """FINGERPRINT FIELD TEST — PRINT PACK {pack_id}

Thank you for volunteering! This takes about 15 minutes.

WHAT THIS IS
Three test sheets. Some carry an invisible fingerprint (tiny line-position
nudges, ~1/4 mm); at least one is an unmarked control. You don't know
which is which — that's the point of the experiment.

WHAT TO DO
1. PRINT all three sheets on a laser or inkjet printer.
   IMPORTANT: print at 100% scale ("Actual size", NOT "Fit to page").
2. PHOTOGRAPH each printed sheet with your phone, flat on a table in
   normal room light, page filling the frame. One photo per sheet.
3. SEND each photo through WhatsApp (e.g. to yourself or a friend) and
   save the received copy — that compressed copy is the valuable one.
4. UPLOAD both files per sheet (original photo + WhatsApp copy) at the
   volunteer page, picking the sheet letter and your capture conditions.

RULES THAT KEEP THE SCIENCE HONEST
- Do not edit, crop, rotate, or "enhance" the photos.
- Do not photograph the screen; photograph the PRINTED sheet.
- One pack per volunteer; capture every sheet at least once.

Your uploads are licensed CC0 (public domain) for research use; your
email is used only to sign in and is never published. Full details on
the volunteer page.
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def encode_sheet(out_png, out_meta, seed, unmarked):
    cmd = [sys.executable, os.path.join(REPO, "encode.py"),
           "--out", out_png, "--meta", out_meta, "--seed", str(seed)]
    if unmarked:
        cmd.append("--unmarked")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"encode.py failed: {r.stderr or r.stdout}")


def png_to_pdf(png_path, pdf_path):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)      # A4 pt
    page.insert_image(page.rect, filename=png_path)
    doc.save(pdf_path)
    doc.close()


import secrets

# Unambiguous alphabet (no 0/O, 1/I) — mirrors engine/packs.py.
_CODE_ALPHABET = "34679ACDEFHJKLMNPRTUVWXY"


def _random_code():
    return "FP" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--out", default=os.path.join("appdata",
                                                  "volunteer_packs"))
    ap.add_argument("--packs-dir", default=os.path.join("demo", "packs"))
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--sequential", action="store_true",
                    help="legacy FP001.. codes (enumerable; only for "
                         "reproducing the committed demo fixtures). Default "
                         "mints unguessable random codes.")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.packs_dir, exist_ok=True)
    index = []
    for k in range(1, args.n + 1):
        pack_id = f"FP{k:03d}" if args.sequential else _random_code()
        pdir = os.path.join(args.out, pack_id)
        priv = os.path.join(pdir, "private")
        pub = os.path.join(pdir, "public")
        os.makedirs(priv, exist_ok=True)
        os.makedirs(pub, exist_ok=True)

        roles = [("v1", args.seed0 + 10 * k + 1, False),
                 ("v2", args.seed0 + 10 * k + 2, False),
                 ("ctrl", args.seed0 + 10 * k + 1, True)]
        rng = random.Random(args.seed0 + k)          # reproducible shuffle
        letters = ["A", "B", "C"]
        rng.shuffle(letters)
        mapping = {}
        for (role, seed, unmarked), letter in zip(roles, letters):
            png = os.path.join(priv, f"{role}.png")
            meta = os.path.join(priv, f"{role}_meta.json")
            encode_sheet(png, meta, seed, unmarked)
            pdf = os.path.join(pub, f"sheet_{letter}.pdf")
            png_to_pdf(png, pdf)
            mapping[letter] = {"role": role, "seed": seed,
                               "unmarked": unmarked,
                               "render_sha256": sha256(png)}
            # the render is fully determined by (seed, unmarked) and
            # re-creatable via encode.py; keeping ~9 MB per sheet on disk
            # (and in git) buys nothing — the hash above pins it
            os.remove(png)
        open(os.path.join(pub, "INSTRUCTIONS.txt"), "w").write(
            INSTRUCTIONS.format(pack_id=pack_id))
        json.dump({"pack_id": pack_id, "mapping": mapping},
                  open(os.path.join(priv, "mapping.json"), "w"), indent=1)

        zpath = os.path.join(args.packs_dir, f"pack_{pack_id}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(pub)):
                z.write(os.path.join(pub, name), name)

        manifest = {os.path.relpath(p, pdir): sha256(p)
                    for root, _, files in os.walk(pdir)
                    for p in [os.path.join(root, f) for f in files]}
        manifest[f"packs/pack_{pack_id}.zip"] = sha256(zpath)
        # the zip IS the distributed artifact and its contents are hashed
        # above; keeping an unzipped copy trebles the disk/git weight
        shutil.rmtree(pub)
        json.dump(manifest, open(os.path.join(priv, "sha256.json"), "w"),
                  indent=1)
        index.append({"pack_id": pack_id,
                      "url": f"packs/pack_{pack_id}.zip"})
        print(f"{pack_id}: sheets {''.join(sorted(mapping))} -> {zpath}")

    json.dump(index, open(os.path.join(args.packs_dir, "index.json"), "w"),
              indent=1)
    print(f"\n{len(index)} packs. Public zips in {args.packs_dir}/ "
          f"(deploy with the demo site); ground truth stays in {args.out}/ "
          f"— NEVER publish that directory.")


if __name__ == "__main__":
    main()
