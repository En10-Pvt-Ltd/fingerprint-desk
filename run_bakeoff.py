#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bakeoff runner. Scores every real capture (and its messaging multipliers)
through the decoder configs, dual-scores each (soft via k_eff and hard-proven
via flip), enforces the split and synthetic-exclusion rules, runs the control
FPR gate, and emits a per-capture CSV plus a summary.

Decoder configs:
  c1     Carrier 1 (line + word shift), fragment-capable, scored THROUGH the
         robust real-capture pipeline (robust_decode/c1_decoder.py). It never
         calls decode.py, which is full-page-synthetic only and fails on real
         captures.
  c2     Carrier 2 learned tile decoder. STUB (trains on the GPU box later); the
         interface is defined so it drops in as run_c2(img, meta) -> result dict.
  fused  per-Tardos-position LLR sum of c1 + c2. Works as c1 alone until c2 lands.

Dual scoring per capture (metrics.py), n and budget from corpus_config.json:
  soft  : k = k_eff(observed LLRs), p_semantics="soft" (no p-factor). The mode
          the real decoder uses.
  flip  : k = observed symbol count, p = ser, p_semantics="flip". The hard-
          decision proven floor. The operating-mode decision is "corpus decides",
          so BOTH are reported, neither is picked.

Rules enforced: synthetic captures never scored; tuning-split docs excluded from
the report summary; controls (unmarked) drive the FPR gate: ANY control that
crosses the courtroom threshold against ANY codeword fails the build (loud, exit
1). c (coalition size) is assumed from framing via corpus_config.json
framing_to_c unless the sidecar overrides it; state that assumption here.

Corpus layout:
  corpus/docs/<doc_id>_meta.json     embedding ground truth (marked + control)
  corpus/captures/<capture_id>.jpg + .json     real photos (intake.py)
  corpus/derived/<...>__msg-*.jpg + .json       messaging multipliers
  corpus/splits.json                 {"tuning":[...], "report":[...]}

Usage:
  python run_bakeoff.py --corpus corpus [--out bakeoff.csv]
"""
import argparse, csv, glob, json, os, sys

from metrics import ser, k_eff, tier
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "robust_decode"))
from c1_decoder import decode_c1                                   # noqa: E402


# ---- decoder configs ---------------------------------------------------------
def run_c1(img, meta):
    return decode_c1(img, meta)


def run_c2(img, meta):
    """Carrier 2 learned tile decoder. Trains on the GPU box; not available here.
    Returns None; the harness treats c2 as absent and fused falls back to c1."""
    return None


def run_fused(c1res, c2res):
    """Per-Tardos-position LLR sum. c1-only until c2 lands."""
    if c2res is None:
        return c1res
    P = len(c1res["llrs"])
    llrs = [c1res["llrs"][i] + c2res["llrs"][i] for i in range(P)]
    decoded = [(-1 if (c1res["decoded"][i] < 0 and c2res["decoded"][i] < 0)
                else (1 if llrs[i] > 0 else 0)) for i in range(P)]
    out = dict(c1res)
    out.update({"llrs": llrs, "decoded": decoded,
                "n_obs": sum(1 for d in decoded if d >= 0)})
    return out


# ---- scoring -----------------------------------------------------------------
def score(res, c, n, budget, betas):
    """Both scorings for one decode result at coalition size c."""
    decoded, truth, llrs = res["decoded"], res["truth"], res["llrs"]
    s, n_obs = ser(decoded, truth)
    obs_llrs = [l for l, d in zip(llrs, decoded) if d >= 0]
    keff = k_eff(obs_llrs) if obs_llrs else 0.0
    row = {"ser": s, "n_obs": n_obs, "k_eff": round(keff, 3)}
    for b in betas:
        st, se = tier(c, keff, 0.0, n, "soft", b, budget)
        ft, fe = tier(c, n_obs, s, n, "flip", b, budget)
        row[f"soft_tier_b{b}"] = st
        row[f"soft_eps1_b{b}"] = se
        row[f"flip_tier_b{b}"] = ft
        row[f"flip_eps1_b{b}"] = fe
    return row


def load_sidecar(img):
    p = img + ".json"
    if os.path.exists(p):
        return json.load(open(p))
    p2 = os.path.splitext(img)[0] + ".json"
    return json.load(open(p2)) if os.path.exists(p2) else {}


def load_doc_metas(corpus):
    metas = {}
    for p in glob.glob(os.path.join(corpus, "docs", "*_meta.json")):
        m = json.load(open(p))
        did = m.get("doc_id") or os.path.basename(p).replace("_meta.json", "")
        metas[did] = m
    return metas


def main():
    repo = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(repo, "corpus_config.json")))
    N = cfg["scoring"]["n"]
    BUDGET = cfg["scoring"]["budget"]
    BETAS = cfg["scoring"]["betas"]
    F2C = cfg["framing_to_c"]

    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--out", default="bakeoff.csv")
    ap.add_argument("--summary", default="bakeoff_summary.md")
    args = ap.parse_args()

    splits = json.load(open(os.path.join(args.corpus, "splits.json")))
    report_docs = set(splits["report"])
    doc_metas = load_doc_metas(args.corpus)
    marked_docs = {d: m for d, m in doc_metas.items() if m.get("marked")}
    if not marked_docs:
        print("no marked docs found; run gen_corpus_docs.py first")
        return

    def coalition(side):
        return int(side.get("c", F2C.get(side.get("framing"), 1)))

    imgs = sorted(glob.glob(os.path.join(args.corpus, "**", "*.jp*g"),
                            recursive=True))
    rows, fpr_hits = [], []

    for img in imgs:
        side = load_sidecar(img)
        if not side or side.get("synthetic"):
            continue                                    # never score synthetic
        did = side.get("doc_id")
        if did not in doc_metas:
            continue
        framing = side.get("framing")
        c = coalition(side)
        split = "report" if did in report_docs else "tuning"
        base = {"capture_id": side.get("capture_id", os.path.basename(img)),
                "doc_id": did, "split": split,
                "framing": framing, "messaging": side.get("applied_chain", "none"),
                "cleanup": side.get("cleanup", "none"),
                "phone": side.get("phone"), "angle_deg": side.get("angle_deg"),
                "lighting": side.get("lighting"), "c": c}

        is_control = not side.get("marked", doc_metas[did].get("marked", False))

        if is_control:
            # FPR: score against EVERY codeword, keep the worst case (the codeword
            # the control comes closest to falsely accusing).
            for dec in ("c1", "fused"):
                worst = None
                for mdid, mmeta in marked_docs.items():
                    r1 = run_c1(img, mmeta)
                    res = r1 if dec == "c1" else run_fused(r1, run_c2(img, mmeta))
                    sc = score(res, c, N, BUDGET, BETAS)
                    key = min(sc[f"flip_eps1_b{b}"] for b in BETAS)
                    accuse = any(sc[f"flip_tier_b{b}"] == "courtroom"
                                 or sc[f"soft_tier_b{b}"] == "courtroom"
                                 for b in BETAS)
                    if worst is None or key < worst[0]:
                        worst = (key, mdid, sc, res, accuse)
                _, vs, sc, res, accuse = worst
                if accuse:
                    fpr_hits.append((base["capture_id"], dec, vs, sc))
                rows.append({**base, "decoder": dec, "is_control": True,
                             "scored_vs": vs, "fpr_accuse": accuse,
                             "n_found": res["n_found"], "n_expected": res["n_expected"],
                             "offset": res["offset"], "line_acc": round(res["line_acc"], 3)
                             if res["line_acc"] == res["line_acc"] else "",
                             "word_acc": round(res["word_acc"], 3)
                             if res["word_acc"] == res["word_acc"] else "", **sc})
        else:
            mmeta = doc_metas[did]
            r1 = run_c1(img, mmeta)
            c2 = run_c2(img, mmeta)
            for dec, res in (("c1", r1), ("c2", c2), ("fused", run_fused(r1, c2))):
                if res is None:                          # c2 stub
                    rows.append({**base, "decoder": dec, "is_control": False,
                                 "scored_vs": did, "fpr_accuse": "",
                                 "n_found": "", "n_expected": "", "offset": "",
                                 "line_acc": "", "word_acc": "", "ser": "",
                                 "n_obs": "", "k_eff": "STUB"})
                    continue
                sc = score(res, c, N, BUDGET, BETAS)
                rows.append({**base, "decoder": dec, "is_control": False,
                             "scored_vs": did, "fpr_accuse": "",
                             "n_found": res["n_found"], "n_expected": res["n_expected"],
                             "offset": res["offset"], "line_acc": round(res["line_acc"], 3)
                             if res["line_acc"] == res["line_acc"] else "",
                             "word_acc": round(res["word_acc"], 3)
                             if res["word_acc"] == res["word_acc"] else "", **sc})

    # ---- write per-capture CSV ----
    cols = ["capture_id", "doc_id", "split", "is_control", "decoder", "scored_vs",
            "framing", "messaging", "cleanup", "phone", "angle_deg", "lighting",
            "c", "n_found", "n_expected", "offset", "line_acc", "word_acc",
            "ser", "n_obs", "k_eff", "fpr_accuse"]
    for b in BETAS:
        cols += [f"soft_eps1_b{b}", f"soft_tier_b{b}",
                 f"flip_eps1_b{b}", f"flip_tier_b{b}"]
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # ---- summary: per (decoder, framing) trace-success, soft and flip ----
    b0 = BETAS[0]
    rep = [r for r in rows if r["split"] == "report" and not r["is_control"]
           and r["decoder"] != "c2"]
    groups = {}
    for r in rep:
        groups.setdefault((r["decoder"], r["framing"]), []).append(r)
    lines = ["# Bakeoff summary", "",
             f"Report set only. n={N}, budget={BUDGET:.0e}, courtroom tier at "
             f"beta={b0}. Trace-success = fraction reaching the courtroom tier.",
             "",
             "| decoder | framing | captures | soft trace-success | flip trace-success |",
             "|---|---|---|---|---|"]
    for (dec, fr), rs in sorted(groups.items()):
        soft = sum(1 for r in rs if r[f"soft_tier_b{b0}"] == "courtroom") / len(rs)
        flip = sum(1 for r in rs if r[f"flip_tier_b{b0}"] == "courtroom") / len(rs)
        lines.append(f"| {dec} | {fr} | {len(rs)} | {soft:.2f} | {flip:.2f} |")
    n_ctrl_scor = sum(1 for r in rows if r["is_control"])
    n_accuse = len(fpr_hits)
    lines += ["", f"Control FPR: {n_accuse} accusation(s) at courtroom across "
              f"{n_ctrl_scor} control scorings."]
    with open(args.summary, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {len(rows)} rows to {args.out} and summary to {args.summary}")
    print(f"pivot on (framing, messaging, cleanup). report captures: {len(rep)}")

    # ---- FPR gate ----
    if fpr_hits:
        print("\n" + "!" * 70)
        print("FPR GATE FAILED: unmarked control(s) crossed the courtroom "
              "threshold. This is a false accusation. THE BUILD FAILS.")
        for cid, dec, vs, sc in fpr_hits:
            print(f"  control {cid} via {dec} falsely accuses {vs}: "
                  f"flip_eps1_b{b0}={sc[f'flip_eps1_b{b0}']:.2e} "
                  f"soft_eps1_b{b0}={sc[f'soft_eps1_b{b0}']:.2e}")
        print("!" * 70)
        sys.exit(1)
    print(f"\nFPR gate PASSED: 0 courtroom-tier accusations across "
          f"{n_ctrl_scor} control scorings.")


if __name__ == "__main__":
    main()
