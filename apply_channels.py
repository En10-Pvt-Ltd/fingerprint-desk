#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Digital channel multipliers applied to REAL captures.

Messaging chains are implemented here (resize + JPEG, parameters matching
observed app behavior as of mid-2026; re-verify before each corpus build,
apps change silently). AI cleanup passes call external tools and are stubbed
with explicit commands, run them on the GPU box.

Rule: these multipliers are applied to real photographs only. Nothing produced
by channel.py (the synthetic simulator) may enter reported numbers.

Usage:
  python apply_channels.py --in capture.jpg --outdir out/ --chains all
"""
import argparse, json, os, subprocess
import cv2

MESSAGING = {
    "none":      [],
    "wa":        [(1600, 78)],
    "wa_x2":     [(1600, 78), (1600, 70)],
    "tg":        [(2560, 87)],
    "wa_then_tg": [(1600, 78), (2560, 87)],
}

# AI cleanup passes: external, run on the GPU box. Strengths per spec v0.2/0.3.
AI_CLEANUP = {
    "none": None,
    "realesrgan_4x": "realesrgan-ncnn-vulkan -i {inp} -o {out} -s 4",
    "sd_img2img_02": "python sd_img2img.py --in {inp} --out {out} --strength 0.2",
    "sd_img2img_04": "python sd_img2img.py --in {inp} --out {out} --strength 0.4",
    "camscanner":    "MANUAL: run CamScanner enhance on device, re-export",
}


def apply_messaging(img, steps):
    for longside, q in steps:
        h, w = img.shape[:2]
        s = longside / max(h, w)
        if s < 1.0:
            img = cv2.resize(img, (int(w * s), int(h * s)),
                             interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    return img


def load_parent_sidecar(inp):
    """A real capture's sidecar (written by intake.py), so derived variants
    inherit doc_id / framing / phone / etc for the pivots and truth mapping."""
    p = inp + ".json"
    if not os.path.exists(p):
        p = os.path.splitext(inp)[0] + ".json"
    return json.load(open(p)) if os.path.exists(p) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--chains", default="all")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    img = cv2.imread(args.inp, cv2.IMREAD_COLOR)
    base = os.path.splitext(os.path.basename(args.inp))[0]

    parent = load_parent_sidecar(args.inp)
    if parent.get("synthetic"):
        # Hard stop: multipliers are for REAL captures only. A synthetic parent
        # would let channel.py output leak into the report set.
        raise SystemExit("refusing: parent sidecar is synthetic:true; "
                         "apply_channels operates on real captures only")

    chains = MESSAGING if args.chains == "all" else \
        {k: MESSAGING[k] for k in args.chains.split(",")}
    for name, steps in chains.items():
        out = os.path.join(args.outdir, f"{base}__msg-{name}.jpg")
        cv2.imwrite(out, apply_messaging(img.copy(), steps),
                    [cv2.IMWRITE_JPEG_QUALITY, 95] if not steps else
                    [cv2.IMWRITE_JPEG_QUALITY, steps[-1][1]])
        # Inherit all parent context, then override the messaging fields. Stays
        # synthetic:false because the source is a real photograph.
        side = dict(parent)
        side.update({"applied_chain": name, "steps": steps,
                     "parent": os.path.basename(args.inp),
                     "synthetic": False})
        json.dump(side, open(out + ".json", "w"), indent=2)
        print("wrote", out)

    print("\nAI cleanup passes (run externally on each msg output):")
    for name, cmd in AI_CLEANUP.items():
        if cmd:
            print(f"  {name}: {cmd}")


if __name__ == "__main__":
    main()
