#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Score volunteer submissions into the weekly wild-corpus scoreboard.

    python app/tools/score_submissions.py --captures captures.csv \
        --images wild_corpus/ --packs appdata/volunteer_packs \
        --out scoreboard/

Inputs: the Supabase `captures` table exported as CSV, the downloaded
`captures` storage bucket (file layout matches original_path /
messaged_path), and the private pack ground truth written by
make_volunteer_packs.py. Reuses the app's validated photo-scoring path
(app/engine/scan.py: prep_clean/prep_robust, observe, score_meta,
binom_p); no decoder logic is reimplemented and no thresholds are tuned
here (P_THRESHOLD / MIN_BITS imported from scan.py).

Pre-registered quality gates, applied mechanically (an excluded row is
listed with its reason, never silently dropped): missing/unreadable
image, decoder line-count validity failure, sha256 duplicate of an
earlier submission, unknown pack or sheet.

Controls ride along in every pack: a control capture is scored against
both marked variants and must read chance; a control clearing the
attribution rule anywhere is a campaign-failing false-positive event and
is reported as such, loudly, per the FPR-zero discipline.

    python app/tools/score_submissions.py --selftest

fabricates one volunteer (renders pack sheets, WhatsApp-grade channel
sim, fake CSV) and asserts marked-high / control-chance. CI runs this.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
REPO = os.path.dirname(APP)
for p in (APP, REPO, os.path.join(REPO, "robust_decode")):
    sys.path.insert(0, p)

import cv2                                     # noqa: E402

from engine import scan                        # noqa: E402

CHANCE_BAND = (0.25, 0.75)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pack(packs_dir, pack_id):
    priv = os.path.join(packs_dir, pack_id, "private")
    mapping = json.load(open(os.path.join(priv, "mapping.json")))["mapping"]
    metas = {}
    for letter, info in mapping.items():
        metas[letter] = {
            "role": info["role"], "unmarked": info["unmarked"],
            "meta": json.load(open(os.path.join(priv,
                                                f"{info['role']}_meta.json"))),
        }
    return mapping, metas


def decode_capture(img_path, n_lines_expected, workdir):
    """Blind decode via the scan.py ladder; returns (line_obs, word_obs,
    path_used) or (None, None, reason)."""
    gray = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None, None, "unreadable image"
    g, bands, _ang, used = scan.prep_clean(gray)
    if len(bands) != n_lines_expected:
        g, bands, _ang, used = scan.prep_robust(img_path, workdir)
    if len(bands) != n_lines_expected:
        return None, None, (f"decoder validity: found {len(bands)} lines, "
                            f"sheet has {n_lines_expected}")
    return (g, bands), used, None


def score_row(row, packs_dir, images_dir, workdir, seen_hashes):
    pack_id = (row.get("pack_id") or "").strip()
    sheet = (row.get("sheet") or "").strip().upper()
    rel = (row.get("messaged_path") or "").strip() \
        or (row.get("original_path") or "").strip()
    out = {"pack_id": pack_id, "sheet": sheet,
           "volunteer": (row.get("volunteer") or "")[:8],
           "phone_tier": row.get("phone_tier"),
           "lighting": row.get("lighting"), "framing": row.get("framing"),
           "messaging": row.get("messaging"), "file": rel}
    try:
        mapping, metas = load_pack(packs_dir, pack_id)
    except (OSError, ValueError, KeyError):
        out["excluded"] = f"unknown pack {pack_id!r}"
        return out
    if sheet not in metas:
        out["excluded"] = f"unknown sheet {sheet!r} for pack {pack_id}"
        return out
    img = os.path.join(images_dir, rel)
    if not rel or not os.path.exists(img):
        out["excluded"] = "image file missing from bucket download"
        return out
    digest = sha256(img)
    if digest in seen_hashes:
        out["excluded"] = (f"duplicate image (same bytes as "
                           f"{seen_hashes[digest]})")
        return out
    seen_hashes[digest] = f"{pack_id}/{sheet}/{out['volunteer']}"

    target = metas[sheet]
    n_lines = target["meta"]["n_lines"]
    decoded, used, reason = decode_capture(img, n_lines, workdir)
    if reason:
        out["excluded"] = reason
        return out
    g, bands = decoded
    ref_line_words = [ln["n_words"] for ln in target["meta"]["lines"]]
    line_obs, word_obs = scan.observe(g, bands, ref_line_words)

    marked_metas = {L: m for L, m in metas.items() if not m["unmarked"]}
    scores = {}
    for L, m in marked_metas.items():
        sc = scan.score_meta(line_obs, word_obs, m["meta"])
        scores[m["role"]] = sc
    out.update({"path_used": used, "is_control": target["unmarked"],
                "role": target["role"], "scores": scores})

    if target["unmarked"]:
        # control: every marked variant must read chance; attribution
        # firing on a control is the campaign-failing FPR event
        fired = [r for r, sc in scores.items()
                 if sc["tot"] >= scan.MIN_BITS and sc["p_value"] is not None
                 and sc["p_value"] * len(scores) <= scan.P_THRESHOLD]
        out["fpr_event"] = fired
    else:
        own = scores[target["role"]]
        others = [sc for r, sc in scores.items() if r != target["role"]]
        out["true_acc"] = own["acc"]
        out["true_line_acc"] = own["line_acc"]
        out["attributed_correctly"] = bool(
            own["tot"] >= scan.MIN_BITS and own["p_value"] is not None
            and own["p_value"] * len(scores) <= scan.P_THRESHOLD
            and all((sc["acc"] or 0) <= (own["acc"] or 0) for sc in others))
    return out


def build_scoreboard(rows):
    sb = {"n_rows": len(rows)}
    included = [r for r in rows if "excluded" not in r]
    excluded = [r for r in rows if "excluded" in r]
    marked = [r for r in included if not r["is_control"]]
    controls = [r for r in included if r["is_control"]]
    sb["volunteers"] = len({r["volunteer"] for r in included})
    sb["packs"] = len({r["pack_id"] for r in included})
    sb["included"] = len(included)
    sb["excluded"] = [{k: r[k] for k in
                       ("pack_id", "sheet", "volunteer", "excluded")}
                      for r in excluded]

    def agg(group_key):
        cells = defaultdict(lambda: [0, 0, 0])
        for r in marked:
            sc = r["scores"][r["role"]]
            c = cells[r.get(group_key) or "?"]
            c[0] += sc["ok"]
            c[1] += sc["tot"]
            c[2] += 1
        return {k: {"acc": round(v[0] / v[1], 3) if v[1] else None,
                    "bits": v[1], "captures": v[2]}
                for k, v in sorted(cells.items())}

    sb["marked"] = {
        "captures": len(marked),
        "overall_acc": (round(sum(r["scores"][r["role"]]["ok"]
                                  for r in marked)
                              / max(1, sum(r["scores"][r["role"]]["tot"]
                                           for r in marked)), 3)
                        if marked else None),
        "attributed_correctly": sum(1 for r in marked
                                    if r.get("attributed_correctly")),
        "by_phone_tier": agg("phone_tier"),
        "by_lighting": agg("lighting"),
        "by_framing": agg("framing"),
        "by_messaging": agg("messaging"),
    }
    ctl_accs = [sc["acc"] for r in controls for sc in r["scores"].values()
                if sc["acc"] is not None]
    fpr = [r for r in controls if r.get("fpr_event")]
    sb["controls"] = {
        "captures": len(controls),
        "mean_agreement_vs_marked": (round(sum(ctl_accs) / len(ctl_accs), 3)
                                     if ctl_accs else None),
        "all_in_chance_band": all(CHANCE_BAND[0] <= a <= CHANCE_BAND[1]
                                  for a in ctl_accs) if ctl_accs else None,
        "FPR_EVENTS": [{k: r[k] for k in
                        ("pack_id", "sheet", "volunteer", "fpr_event")}
                       for r in fpr],
    }
    return sb


def render_md(sb):
    L = []
    L.append("# Wild-corpus scoreboard\n")
    L.append(f"Volunteers: **{sb['volunteers']}**  |  packs touched: "
             f"**{sb['packs']}**  |  captures scored: **{sb['included']}** "
             f"(excluded: {len(sb['excluded'])})\n")
    m = sb["marked"]
    L.append(f"## Marked sheets\n\nCaptures: {m['captures']}  |  overall "
             f"bit accuracy: **{m['overall_acc']}**  |  correctly "
             f"attributed: {m['attributed_correctly']}/{m['captures']}\n")
    for dim in ("phone_tier", "lighting", "framing", "messaging"):
        cells = m[f"by_{dim}"]
        if not cells:
            continue
        L.append(f"\n### by {dim.replace('_', ' ')}\n")
        L.append("| value | accuracy | bits | captures |")
        L.append("|---|---|---|---|")
        for k, v in cells.items():
            L.append(f"| {k} | {v['acc']} | {v['bits']} | {v['captures']} |")
    c = sb["controls"]
    L.append(f"\n## Controls\n\nCaptures: {c['captures']}  |  mean "
             f"agreement vs marked codewords: "
             f"{c['mean_agreement_vs_marked']}  |  all in chance band: "
             f"{c['all_in_chance_band']}\n")
    if c["FPR_EVENTS"]:
        L.append("\n**FALSE-POSITIVE EVENT(S) ON CONTROLS — the campaign "
                 "report FAILS its own gate until these are explained:**\n")
        for e in c["FPR_EVENTS"]:
            L.append(f"- {e}")
    else:
        L.append("\nNo control crossed the attribution rule (the "
                 "FPR-must-be-zero gate holds).")
    if sb["excluded"]:
        L.append("\n## Excluded submissions (pre-registered gates)\n")
        for e in sb["excluded"]:
            L.append(f"- {e['pack_id']}/{e['sheet']} "
                     f"({e['volunteer']}): {e['excluded']}")
    L.append("")
    return "\n".join(L)


def selftest():
    """Fabricate one volunteer: render two pack sheets (one marked, one
    control) at print resolution, put them through the WhatsApp-grade
    channel sim, and score the fake submission end to end."""
    import fitz
    from engine import channel_sim

    td = tempfile.mkdtemp(prefix="score_selftest_")
    packs = os.path.join(td, "packs")
    images = os.path.join(td, "bucket", "vol")
    os.makedirs(images)
    # build one pack with the real tool
    import subprocess
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "make_volunteer_packs.py"),
         "--n", "1", "--sequential", "--out", packs,   # deterministic FP001
         "--packs-dir", os.path.join(td, "zips")],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pack generation failed: {r.stderr[-400:]}")
    mapping, metas = load_pack(packs, "FP001")
    marked_letter = next(L for L, m in metas.items() if not m["unmarked"])
    ctrl_letter = next(L for L, m in metas.items() if m["unmarked"])

    import zipfile
    zf = zipfile.ZipFile(os.path.join(td, "zips", "pack_FP001.zip"))
    rows = []
    for letter in (marked_letter, ctrl_letter):
        pdfb = zf.read(f"sheet_{letter}.pdf")
        doc = fitz.open(stream=pdfb, filetype="pdf")
        png = os.path.join(td, f"{letter}.png")
        doc[0].get_pixmap(dpi=300).save(png)
        doc.close()
        wd = os.path.join(td, f"ch_{letter}")
        os.makedirs(wd)
        cap, _ = channel_sim.simulate(png, wd, "whatsapp")
        dst = f"vol/{letter}.jpg"
        shutil.copy(cap, os.path.join(images, f"{letter}.jpg"))
        rows.append({"volunteer": "selftest-vol", "pack_id": "FP001",
                     "sheet": letter, "phone_tier": "mid", "angle": "0",
                     "lighting": "office", "framing": "full",
                     "messaging": "wa", "original_path": "",
                     "messaged_path": dst, "consent": "true"})

    seen = {}
    wd = os.path.join(td, "work")
    os.makedirs(wd)
    scored = [score_row(r, packs, os.path.join(td, "bucket"), wd, seen)
              for r in rows]
    sb = build_scoreboard(scored)
    print(render_md(sb))
    mrow = next(r for r in scored if not r.get("is_control", True))
    crow = next(r for r in scored if r.get("is_control"))
    assert "excluded" not in mrow, f"marked excluded: {mrow}"
    assert "excluded" not in crow, f"control excluded: {crow}"
    assert (mrow["true_line_acc"] or 0) >= 0.9, \
        f"marked line accuracy too low: {mrow['true_line_acc']}"
    assert mrow["attributed_correctly"], "marked sheet not attributed"
    assert not crow["fpr_event"], f"control fired attribution: {crow}"
    shutil.rmtree(td, ignore_errors=True)
    print("SELFTEST PASSED: marked sheet attributed, control at chance.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures")
    ap.add_argument("--images")
    ap.add_argument("--packs", default=os.path.join(REPO, "appdata",
                                                    "volunteer_packs"))
    ap.add_argument("--out", default="scoreboard")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.captures or not args.images:
        ap.error("--captures and --images are required (or --selftest)")

    rows = list(csv.DictReader(open(args.captures, encoding="utf-8-sig")))
    os.makedirs(args.out, exist_ok=True)
    wd = os.path.join(args.out, "work")
    os.makedirs(wd, exist_ok=True)
    seen = {}
    scored = []
    for i, row in enumerate(rows):
        r = score_row(row, args.packs, args.images, wd, seen)
        state = r.get("excluded") or (
            f"acc={r.get('true_acc')}" if not r.get("is_control")
            else f"control agreement={[sc['acc'] for sc in r['scores'].values()]}")
        print(f"[{i + 1}/{len(rows)}] {r['pack_id']}/{r['sheet']}: {state}")
        scored.append(r)
    sb = build_scoreboard(scored)
    json.dump({"rows": scored, "scoreboard": sb},
              open(os.path.join(args.out, "scoreboard.json"), "w"), indent=1)
    md = render_md(sb)
    open(os.path.join(args.out, "scoreboard.md"), "w").write(md)
    print("\n" + md)
    print(f"Written to {args.out}/scoreboard.md and scoreboard.json")


if __name__ == "__main__":
    main()
