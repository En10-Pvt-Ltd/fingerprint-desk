#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Synthetic capture-channel simulator for pre-print sanity checks ONLY.
Real go/no-go numbers come from real print-photograph-WhatsApp captures.

Applies: small rotation, mild perspective, Gaussian blur, downscale to a
target long side (WhatsApp ~1600 px, Telegram ~2560 px), JPEG recompression.

Usage:
  python channel.py --in marked.png --out captured.jpg \
      [--rot 0.4] [--persp 0.004] [--blur 1.0] [--longside 1600] [--quality 78]
"""
import argparse
import numpy as np
import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rot", type=float, default=0.4)
    ap.add_argument("--persp", type=float, default=0.004)
    ap.add_argument("--blur", type=float, default=1.0)
    ap.add_argument("--longside", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=78)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    img = cv2.imread(args.inp, cv2.IMREAD_GRAYSCALE)
    h, w = img.shape

    # Rotation.
    M = cv2.getRotationMatrix2D((w / 2, h / 2), args.rot, 1.0)
    img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                         borderValue=255)

    # Mild perspective: jitter the four corners by up to persp * dim.
    j = args.persp
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + rng.uniform(-1, 1, (4, 2)).astype(np.float32) * \
        np.float32([w * j, h * j])
    P = cv2.getPerspectiveTransform(src, dst)
    img = cv2.warpPerspective(img, P, (w, h), flags=cv2.INTER_LINEAR,
                              borderValue=255)

    # Optics blur.
    if args.blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), args.blur)

    # Messaging downscale + JPEG.
    scale = args.longside / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    cv2.imwrite(args.out, img, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
    print(f"channel: rot={args.rot} persp={args.persp} blur={args.blur} "
          f"longside={args.longside} q={args.quality} -> {args.out} "
          f"({img.shape[1]}x{img.shape[0]})")


if __name__ == "__main__":
    main()
