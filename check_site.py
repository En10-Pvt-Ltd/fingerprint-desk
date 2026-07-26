#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Demo-site verification gate. Run after make_demo_assets.py:

    python check_site.py [--allow-missing-eprocess]

Checks (any failure exits nonzero):
  1. Link audit: every asset referenced by demo/index.html and demo/app.js
     exists on disk; the two script/style links resolve.
  2. Em-dash gate: no U+2014 anywhere under demo/ (html, css, js, json, md),
     which includes generated JSON and any copy imported from paper docs.
  3. Primacy gate: the phrase "first in" appears nowhere under demo/.
  4. Required words: "simulated" and "fictional" present in index.html, the
     three canonical result labels present verbatim, the three limitations
     present, and the corrected-factor note present.
  5. Number provenance: every digit-bearing token in index.html's visible
     text (plus alt/aria-label attributes) and in app.js string literals
     must be structural (whitelist) or derivable from a number in the
     generated JSON assets. No hand-edited result numbers can survive this.
  6. Provenance completeness: the Act 3 headline numbers exist in
     provenance.json together with the command lines that produced them.
"""
import argparse
import glob
import json
import os
import re
import sys
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(REPO, "demo")
ASSETS = os.path.join(DEMO, "assets")

FAILS = []


def fail(msg):
    FAILS.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg):
    print(f"  ok    {msg}")


# ---- collect text -------------------------------------------------------------
class TextCollector(HTMLParser):
    """Visible text plus alt/aria-label attribute values; other attributes
    (dimensions, paths, ids) are structural and excluded from the number scan."""
    def __init__(self):
        super().__init__()
        self.chunks = []
        self.refs = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        for k in ("alt", "aria-label"):
            if d.get(k):
                self.chunks.append(d[k])
        for k in ("src", "href"):
            if d.get(k) and not d[k].startswith(("http", "#", "mailto:")):
                self.refs.append(d[k])

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.chunks.append(data)


def js_strings(src):
    return re.findall(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`((?:[^`\\]|\\.)*)`',
                      src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-missing-eprocess", action="store_true")
    args = ap.parse_args()

    index_path = os.path.join(DEMO, "index.html")
    app_path = os.path.join(DEMO, "app.js")
    html = open(index_path, encoding="utf-8").read()
    js = open(app_path, encoding="utf-8").read()

    tc = TextCollector()
    tc.feed(html)
    text = " ".join(tc.chunks)

    # ---- 1. link audit ----------------------------------------------------
    print("[1] link audit")
    refs = set(tc.refs)
    for m in re.finditer(r'["`\']assets/([^"`\'$]+?)["`\']', js):
        refs.add("assets/" + m.group(1))
    for m in re.finditer(r'assets/dec_\$\{t\.key\}_marked\.json', js):
        for t in ("clean", "wa", "double", "harsh"):
            refs.add(f"assets/dec_{t}_marked.json")
    optional = {"assets/eprocess_trajectories.json"} \
        if args.allow_missing_eprocess else set()
    for r in sorted(refs):
        p = os.path.join(DEMO, r.replace("/", os.sep))
        if os.path.exists(p):
            ok(f"exists: {r}")
        elif r in optional:
            print(f"  WARN  pending (allowed): {r}")
        else:
            fail(f"broken link: {r}")
    # gallery images swapped at runtime from decode JSON "image" fields
    for jp in glob.glob(os.path.join(ASSETS, "dec_*_marked.json")):
        img = json.load(open(jp)).get("image")
        if img and not os.path.exists(os.path.join(ASSETS, img)):
            fail(f"gallery image missing: assets/{img} (from {os.path.basename(jp)})")

    # ---- 2 + 3. em-dash and primacy gates, all demo text files -------------
    print("[2] em-dash gate  /  [3] primacy gate")
    scan_files = [f for pat in ("**/*.html", "**/*.css", "**/*.js",
                                "**/*.json", "**/*.md")
                  for f in glob.glob(os.path.join(DEMO, pat), recursive=True)]
    for f in scan_files:
        s = open(f, encoding="utf-8", errors="replace").read()
        rel = os.path.relpath(f, DEMO)
        if "—" in s:
            fail(f"em-dash in {rel}")
        if re.search(r"first\s+in\b", s, re.I):
            fail(f'"first in" phrase in {rel}')
    ok(f"scanned {len(scan_files)} files under demo/")

    # ---- 4. required words --------------------------------------------------
    print("[4] required words and labels")
    required = {
        '"simulated" present': "simulated" in html.lower(),
        '"fictional" present': "fictional" in html.lower(),
        "label: simulated channel": "simulated channel" in html,
        "label: real capture (single dry-run print)":
            "real capture (single dry-run print)" in html,
        "label: Monte Carlo simulation of the accusation statistic":
            "Monte Carlo simulation\n        of the accusation statistic"
            in html or "Monte Carlo simulation of the accusation statistic"
            in re.sub(r"\s+", " ", html),
        "limitation: retyping": "retyp" in html.lower(),
        "limitation: pre-differentiation": "differentiated" in html.lower(),
        "limitation: fragments are leads": "investigative leads" in html.lower(),
        "corrected factor note (1 - 2p)": "(1 - 2p)" in html,
        "pending corpus validation stated": "pending" in html.lower(),
    }
    for name, cond in required.items():
        ok(name) if cond else fail(name)

    # ---- 5. number provenance ----------------------------------------------
    print("[5] number provenance")
    allowed = set()

    def add(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            allowed.add(round(float(v), 6))
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
        elif isinstance(v, list):
            for x in v:
                add(x)

    for jp in glob.glob(os.path.join(ASSETS, "*.json")):
        try:
            add(json.load(open(jp, encoding="utf-8")))
        except ValueError:
            fail(f"unparseable JSON asset: {os.path.basename(jp)}")

    def variants(x):
        vs = {x}
        vs.add(round(x, 6))
        if 0 <= x <= 1:
            vs.add(round(x * 100, 6))          # percent form
        if x != 0:
            vs.add(round(x / 100, 6))          # value shown as percent
        return vs

    def allowed_num(x):
        return any(round(v, 6) in allowed or
                   any(abs(v - a) < 5e-4 for a in allowed)
                   for v in variants(x))

    WHITELIST = {"2024", "0417"} | {str(i) for i in range(0, 13)} | {"11"}
    tokens = []
    for tok in re.findall(r"\d[\d.,e+\-/%]*", text):
        tokens.append(("index.html", tok))
    for grp in js_strings(js):
        s = next(g for g in grp if g is not None and g != "") if any(grp) else ""
        s = re.sub(r"#[0-9a-fA-F]{3,8}\b", "", s)      # hex colors, structural
        for tok in re.findall(r"\d[\d.]*", s):
            tokens.append(("app.js string", tok))
    bad = []
    for src, tok in tokens:
        t = tok.rstrip(".,")
        if t in WHITELIST:
            continue
        parts = re.split(r"[/]", t)
        okflag = True
        for p in parts:
            p = p.rstrip("%").rstrip(".,")
            if not p or p in WHITELIST:
                continue
            try:
                x = float(p.replace(",", ""))
            except ValueError:
                continue
            if not allowed_num(x):
                okflag = False
        if not okflag:
            bad.append((src, tok))
    if bad:
        for src, tok in bad:
            fail(f"number without provenance in {src}: {tok!r}")
    else:
        ok(f"{len(tokens)} digit tokens all provenance-backed or structural")

    # ---- 6. provenance completeness -----------------------------------------
    print("[6] provenance completeness (Act 3 headline numbers + commands)")
    prov_path = os.path.join(ASSETS, "provenance.json")
    if not os.path.exists(prov_path):
        fail("assets/provenance.json missing")
    else:
        prov = json.load(open(prov_path, encoding="utf-8"))
        nums, entries = prov["numbers"], {e["id"]: e for e in prov["entries"]}
        for key in ("wa_marked_line_acc", "wa_marked_word_acc",
                    "wa_marked_payload_ok", "wa_control_line_acc",
                    "wa_control_word_acc", "real_marked_line_acc",
                    "real_control_line_acc"):
            ok(f"number present: {key} = {nums[key]}") if key in nums \
                else fail(f"number missing from provenance: {key}")
        for eid in ("encode_marked", "channel_wa_marked_hop0",
                    "decode_wa_marked", "decode_wa_control",
                    "real_marked", "real_control", "tiers", "test_metrics"):
            e = entries.get(eid)
            if e and e.get("cmd"):
                ok(f"command recorded: {eid}")
            else:
                fail(f"command line missing from provenance: {eid}")
        if not prov.get("eprocess_built"):
            if args.allow_missing_eprocess:
                print("  WARN  e-process assets pending (allowed for interim build)")
            else:
                fail("e-process assets not built (stage0/eprocess.py pending)")
        elif "eprocess_selftest" not in entries:
            fail("eprocess self-test output missing from provenance")

    print()
    if FAILS:
        print(f"CHECK FAILED: {len(FAILS)} problem(s).")
        sys.exit(1)
    print("ALL SITE CHECKS PASSED")


if __name__ == "__main__":
    main()
