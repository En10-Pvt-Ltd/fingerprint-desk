#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate the Phase B document set: 5 marked variants (distinct codewords) +
5 unmarked controls, each rendered by encode.py with ground-truth meta JSON.

Printer and stock are NOT baked into the PNG (spec v0.3 Section 3.1): they are
recorded at capture time by intake.py. One physical print of each doc is made on
each available (printer, stock) at capture time, which multiplies these 10 base
documents up toward the 35-document target as the rig grows.

Each meta is tagged with doc_id / seed / variant / marked so the harness can map
captures to truth. Also writes splits.json (variants 1-3 tuning, 4-5 + all
controls report) and registers the existing dry-run captures' docs so the
end-to-end dry run has truth to score against.

Usage:
  python gen_corpus_docs.py [--corpus corpus]
"""
import argparse, json, os, shutil, subprocess, sys

REPO = os.path.dirname(os.path.abspath(__file__))
N_VARIANTS = 5
N_CONTROLS = 5
VARIANT_SEED0 = 1000       # variant v seed = 1000 + v
CONTROL_SEED0 = 2000       # control c seed = 2000 + c


def encode(out_png, out_meta, seed, unmarked):
    cmd = [sys.executable, os.path.join(REPO, "encode.py"),
           "--out", out_png, "--meta", out_meta, "--seed", str(seed)]
    if unmarked:
        cmd.append("--unmarked")
    subprocess.run(cmd, check=True)


def tag_meta(path, **fields):
    m = json.load(open(path))
    m.update(fields)
    json.dump(m, open(path, "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus")
    args = ap.parse_args()
    docs = os.path.join(args.corpus, "docs")
    os.makedirs(docs, exist_ok=True)

    report, tuning = [], []

    # 5 marked variants, distinct codewords via distinct seeds.
    for v in range(1, N_VARIANTS + 1):
        did = f"v{v}"
        seed = VARIANT_SEED0 + v
        encode(os.path.join(docs, f"{did}.png"),
               os.path.join(docs, f"{did}_meta.json"), seed, unmarked=False)
        tag_meta(os.path.join(docs, f"{did}_meta.json"),
                 doc_id=did, seed=seed, variant=v, marked=True)
        (tuning if v <= 3 else report).append(did)   # 1-3 tuning, 4-5 report

    # 5 unmarked controls (report set, drive the FPR gate).
    for c in range(1, N_CONTROLS + 1):
        did = f"ctrl{c}"
        seed = CONTROL_SEED0 + c
        encode(os.path.join(docs, f"{did}.png"),
               os.path.join(docs, f"{did}_meta.json"), seed, unmarked=True)
        tag_meta(os.path.join(docs, f"{did}_meta.json"),
                 doc_id=did, seed=seed, marked=False)
        report.append(did)

    # Dry-run docs: register the existing validated captures' ground truth so the
    # end-to-end dry run can score before any new physical capture. DELETE these
    # (and their captures) before the real campaign; they are not part of the 35.
    dry = []
    for src_meta, did, marked in [("meta.json", "dry_marked", True),
                                  ("control_meta.json", "dry_control", False)]:
        if os.path.exists(os.path.join(REPO, src_meta)):
            dst = os.path.join(docs, f"{did}_meta.json")
            shutil.copyfile(os.path.join(REPO, src_meta), dst)
            tag_meta(dst, doc_id=did, marked=marked, dry_run=True)
            report.append(did)
            dry.append(did)

    splits = {"tuning": tuning, "report": report,
              "_note": "variants 1-3 tuning, 4-5 + all controls report; no "
                       "physical page shared across splits. dry_* are dry-run "
                       "placeholders, remove before the real campaign.",
              "dry_run_docs": dry}
    json.dump(splits, open(os.path.join(args.corpus, "splits.json"), "w"),
              indent=2)

    print(f"generated {N_VARIANTS} marked + {N_CONTROLS} control docs in {docs}")
    print(f"tuning={tuning}  report={report}")
    print(f"dry-run docs registered: {dry}")


if __name__ == "__main__":
    main()
