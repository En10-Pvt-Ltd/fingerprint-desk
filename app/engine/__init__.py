# SPDX-License-Identifier: Apache-2.0
"""Engine package: makes the research repo importable as a library.

The research scripts stay at the repo root (encode.py, decode.py) and in
robust_decode/; this package inserts both onto sys.path so the app reuses
their functions directly instead of duplicating the public convention.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (REPO, os.path.join(REPO, "robust_decode")):
    if p not in sys.path:
        sys.path.insert(0, p)

APPDATA = os.environ.get("FF_APPDATA", os.path.join(REPO, "appdata"))
