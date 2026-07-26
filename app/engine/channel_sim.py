# SPDX-License-Identifier: Apache-2.0
"""Simulate-leak presets: run a generated page through channel.py (the
research repo's synthetic capture simulator) via subprocess, so the script
stays the single source of truth for the channel model. Everything produced
here is labeled "simulated channel"; it is a decoder-logic demonstration,
never a physical result (see docs/method.md).
"""
import os
import subprocess
import sys

from . import REPO

CHANNEL = os.path.join(REPO, "channel.py")

# Same presets as demo/make_demo_assets.py.
PRESETS = {
    "clean": [],
    "whatsapp": [["--rot", "0.4", "--persp", "0.004", "--blur", "1.0",
                  "--longside", "1600", "--quality", "78"]],
    "double": [["--rot", "0.8", "--persp", "0.006", "--blur", "1.2",
                "--longside", "1600", "--quality", "74"],
               ["--rot", "0.0", "--persp", "0.0", "--blur", "0.3",
                "--longside", "1600", "--quality", "70"]],
    "harsh": [["--rot", "1.5", "--persp", "0.004", "--blur", "1.8",
               "--longside", "1200", "--quality", "65"]],
}


def simulate(src_png, workdir, preset):
    """Apply the preset hops to src_png inside workdir. Returns
    (final_image_path, [command strings for the log])."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    hops = PRESETS[preset]
    cmds = []
    if not hops:
        return src_png, ["(clean: decoded directly, no channel applied)"]
    src = src_png
    for i, hop in enumerate(hops):
        dst = os.path.join(workdir, f"hop{i}.jpg")
        cmd = [sys.executable, CHANNEL, "--in", src, "--out", dst] + hop
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"channel.py failed: {r.stderr or r.stdout}")
        cmds.append(" ".join(os.path.basename(c) if os.sep in str(c) else str(c)
                             for c in cmd))
        src = dst
    return src, cmds
