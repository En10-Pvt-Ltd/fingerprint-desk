#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Logged capture intake. Every physical photo lands with full metadata.

Copies a photo into corpus/captures/ under a deterministic capture_id and writes
a sidecar JSON with the full capture context. Validates every enum against
corpus_config.json so typos cannot silently corrupt the pivots. Multiple phones,
printers, and stocks are first-class: they are recorded here, not baked into the
document PNG.

capture_id = <doc_id>_<printer>_<stock>_<phone>_a<angle>_<lighting>_<framing>[_<tag>]
so the same physical condition re-shot gets a distinct id via --tag.

Usage:
  python intake.py --img photo.jpg --doc_id v4 --printer laser_mono_600 \
      --stock plain_80gsm --phone flagship --angle 15 --lighting office \
      --framing full [--tag 2] [--corpus corpus] [--screen-reshoot]
"""
import argparse, json, os, shutil, datetime


def load_config(repo):
    return json.load(open(os.path.join(repo, "corpus_config.json")))


def main():
    repo = os.path.dirname(os.path.abspath(__file__))
    cfg = load_config(repo)
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--doc_id", required=True)
    ap.add_argument("--printer", required=True, choices=cfg["printers"])
    ap.add_argument("--stock", required=True, choices=cfg["stocks"])
    ap.add_argument("--phone", required=True, choices=cfg["phones"])
    ap.add_argument("--angle", required=True, type=int, choices=cfg["angles"])
    ap.add_argument("--lighting", required=True, choices=cfg["lighting"])
    ap.add_argument("--framing", required=True, choices=cfg["framings"])
    ap.add_argument("--lux", type=float, default=None, help="optional measured lux")
    ap.add_argument("--screen-reshoot", action="store_true",
                    help="photo of a screen, not paper (attack-surface probe)")
    ap.add_argument("--tag", default="", help="disambiguator for repeat shots")
    ap.add_argument("--corpus", default="corpus")
    args = ap.parse_args()

    if not os.path.exists(args.img):
        ap.error(f"image not found: {args.img}")
    docs = os.path.join(args.corpus, "docs")
    meta_path = os.path.join(docs, f"{args.doc_id}_meta.json")
    if not os.path.exists(meta_path):
        ap.error(f"no ground-truth meta for doc_id {args.doc_id!r} "
                 f"({meta_path}); run gen_corpus_docs.py first")
    doc_meta = json.load(open(meta_path))

    caps = os.path.join(args.corpus, "captures")
    os.makedirs(caps, exist_ok=True)
    parts = [args.doc_id, args.printer, args.stock, args.phone,
             f"a{args.angle}", args.lighting, args.framing]
    if args.tag:
        parts.append(str(args.tag))
    capture_id = "_".join(parts)
    ext = os.path.splitext(args.img)[1].lower() or ".jpg"
    dst = os.path.join(caps, capture_id + ext)
    shutil.copyfile(args.img, dst)

    side = {
        "capture_id": capture_id, "doc_id": args.doc_id,
        "variant": doc_meta.get("variant"), "seed": doc_meta.get("seed"),
        "marked": bool(doc_meta.get("marked", not doc_meta.get("unmarked", False))),
        "printer": args.printer, "stock": args.stock, "phone": args.phone,
        "angle_deg": args.angle, "lighting": args.lighting, "lux_est": args.lux,
        "framing": args.framing, "screen_reshoot": bool(args.screen_reshoot),
        "applied_chain": "none", "cleanup": "none", "synthetic": False,
        "parent": None, "timestamp": datetime.datetime.now().isoformat(),
    }
    json.dump(side, open(dst + ".json", "w"), indent=2)
    print(f"intake: {args.img} -> {dst}")
    print(f"  capture_id={capture_id} marked={side['marked']} "
          f"framing={args.framing} phone={args.phone}")


if __name__ == "__main__":
    main()
