#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Corpus-harness metrics (Tardos-fallback forensic tier calculator).

Implements:
  - ser(): raw symbol error rate.
  - k_eff(): effective observed-symbol count from per-symbol LLRs, defined as
    the sum of per-symbol binary channel capacities implied by the LLR
    magnitudes. This is the number that plugs into the analytic tier formula.
  - epsilon1(): the master forensic inequality with the detection-power term,
        Qinv(epsilon_1 / n) <= (2/pi) * f(p) * sqrt(k) / c  -  Qinv(1 - beta)
    solved for epsilon_1, where f(p) is the drift factor set by p_semantics.
    beta = 0.5 reproduces the v0.2 operating point.
  - pmax(): inverts the inequality for the largest error rate p that still
    clears a stated false-accusation budget. This is what the forensic table
    reports and what the tests assert on.
  - tier(): maps (c, k, p, n, p_semantics, beta, budget) to the achievable
    epsilon_1 and a label.

--------------------------------------------------------------------------
p-semantics: erasure vs flip vs soft (this block encodes the fix)
--------------------------------------------------------------------------
The guilty drift is mu_g = (2/pi) * f(p) * sqrt(k) / c. The scalar factor f(p)
is NOT universal; it depends on how the symbol-error rate p enters the score,
and getting it wrong silently halves the tolerated error rate. The three modes:

  "erasure"  f(p) = (1 - p).  Correct ONLY when unreadable symbols are dropped
             (erased) and never scored. A missing symbol contributes 0 drift,
             so a fraction p of symbols simply do not help. Nothing scores
             AGAINST the true source.

  "flip"     f(p) = (1 - 2p).  Correct for a hard-decision channel where a wrong
             symbol is still scored: a flipped symbol actively scores against
             the true source, so each error costs TWICE (one lost vote plus one
             adverse vote). At p >= 0.5 there is no positive drift and the source
             is unattributable, so epsilon1 = 1.0. This matches the Stage 0
             single-source path (chernoff.py), which also uses (1 - 2p).

  "soft"     No scalar p-factor at all. The caller passes the effective symbol
             count k = k_eff(LLRs); per-symbol reliability is already folded
             into that capacity sum, so multiplying by another f(p) would double
             count. This is the information-theoretically correct operating mode
             and the one the real decoder uses (soft-LLR fusion). epsilon1 is
             independent of the p argument in this mode.

THE BUG THIS FIXES: the v0.2/v0.3 cells used (1 - p) while feeding p as a hard
symbol-error rate. That is the erasure factor applied to a flip channel, so the
tabulated courtroom tolerance was about double the truth. p_semantics is now a
REQUIRED argument (no silent default) precisely because the implicit default is
what caused the bug. Recommended production mode is "soft"; "flip" is the right
hard-decision floor; "erasure" applies only if the decoder truly erases.

All cells produced from these functions are INTERLEAVING-CALIBRATED
PLACEHOLDERS (see spec v0.3 Section 2): at small c the true marking-assumption
worst case can be worse than interleaving (cells optimistic), while the
physically realizable position-blind region-routing colluder is weaker
(cells conservative). The benchmark fixes the true constant.
"""
import math
import numpy as np

SQRT2 = math.sqrt(2.0)
P_SEMANTICS = ("erasure", "flip", "soft")


def Q(z):
    return 0.5 * math.erfc(z / SQRT2)


def Qinv(p, lo=-10.0, hi=40.0):
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0,1)")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if Q(mid) > p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def ser(decoded, truth):
    decoded, truth = np.asarray(decoded), np.asarray(truth)
    ok = decoded >= 0                       # -1 marks erasure
    if ok.sum() == 0:
        return 1.0, 0
    return float((decoded[ok] != truth[ok]).mean()), int(ok.sum())


def k_eff(llrs):
    """Sum of per-symbol capacities of the BSC implied by each |LLR|.
    |L| maps to flip prob q = 1/(1+e^|L|), capacity = 1 - H2(q)."""
    llrs = np.abs(np.asarray(llrs, dtype=np.float64))
    q = 1.0 / (1.0 + np.exp(llrs))
    q = np.clip(q, 1e-12, 0.5)
    h2 = -q * np.log2(q) - (1 - q) * np.log2(1 - q)
    return float(np.sum(1.0 - h2))


def drift_factor(p, p_semantics):
    """Scalar f(p) multiplying the interleaving drift. See the module header
    for why erasure=(1-p), flip=(1-2p), soft=1 (reliability already in k)."""
    if p_semantics == "erasure":
        return 1.0 - p
    if p_semantics == "flip":
        return 1.0 - 2.0 * p            # caller guards p >= 0.5 (no positive drift)
    if p_semantics == "soft":
        return 1.0                      # no p-factor; k = k_eff carries reliability
    raise ValueError(f"p_semantics must be one of {P_SEMANTICS}, "
                     f"got {p_semantics!r}")


def epsilon1(c, k, p, n, p_semantics, beta=0.5):
    """Achievable total false-accusation probability at detection power beta.

    p_semantics is REQUIRED (one of 'erasure', 'flip', 'soft'); see the module
    header. beta=0.5 is the mu_g = Z operating point (attribution succeeds half
    the time for the average colluder); the false-accusation side is rigorous
    regardless of beta. In 'flip' mode p >= 0.5 yields no positive drift, so the
    source is unattributable and epsilon1 = 1.0. In 'soft' mode the result is
    independent of p by construction.
    """
    if p_semantics == "flip" and p >= 0.5:
        return 1.0
    zstar = drift_factor(p, p_semantics) * (2.0 / math.pi) * math.sqrt(k) / c
    zstar -= Qinv(1.0 - beta)           # power cost: mu_g >= Z + z_beta sqrt(k)
    if zstar <= 0:
        return 1.0
    return min(1.0, n * Q(zstar))


def pmax(c, k, n, budget, beta, p_semantics):
    """Largest symbol-error rate p that still clears the false-accusation budget.

    Inverts the master inequality at equality:
        f(p) * (2/pi) * sqrt(k) / c  =  Qinv(budget / n) + Qinv(1 - beta)
    A returned value <= 0 means the cell is infeasible: the budget cannot be met
    even at zero error. 'soft' has no p-dependence, so pmax is undefined for it.
    """
    if p_semantics == "soft":
        raise ValueError("pmax is undefined for 'soft': soft mode ignores p "
                         "(reliability is folded into k via k_eff()).")
    D = (2.0 / math.pi) * math.sqrt(k) / c
    needed = (Qinv(budget / n) + Qinv(1.0 - beta)) / D   # min drift factor
    if p_semantics == "erasure":
        return 1.0 - needed                              # 1 - p = needed
    if p_semantics == "flip":
        return 0.5 * (1.0 - needed)                      # 1 - 2p = needed
    raise ValueError(f"p_semantics must be one of {P_SEMANTICS}, "
                     f"got {p_semantics!r}")


def tier(c, k, p, n, p_semantics, beta=0.5, budget=1e-6):
    """Map a cell to a forensic tier and its achieved epsilon1.

    budget is the courtroom-tier false-accusation allocation. Under the Stage 0
    ledger split the Tardos fallback gets budget = 5e-7 (not the full 1e-6),
    because Stage 0 spends the other half; pass budget=5e-7 in that case.
    """
    e1 = epsilon1(c, k, p, n, p_semantics, beta)
    tiers = [(budget, "courtroom"), (1e-3, "strong lead"), (5e-2, "weak lead")]
    for thr, label in tiers:
        if e1 <= thr:
            return label, e1
    return "no guarantee", e1


# ---- Forensic table: Tardos-fallback pmax cells -------------------------------
# Region scales (name, c, k). Tardos fallback only; the Stage 0 c-independent
# single-source table lives in stage0-soundness.md and is a SEPARATE artifact.
TABLE_ROWS = [
    ("full paper", 5, 8000),
    ("single page", 2, 1000),
    ("single question (c=1)", 1, 200),
    ("single question (c=2)", 2, 200),
]
TABLE_N = 5000
TABLE_BUDGET = 5e-7          # Stage 0 ledger split: Tardos path gets half of 1e-6


def _fmt(v):
    return f"{v:.3f}" if v > 0 else "infeasible"


def build_table():
    """Return (rows, markdown) for the pmax forensic table under both
    erasure and flip semantics at beta 0.5 and 0.9."""
    rows = []
    for name, c, k in TABLE_ROWS:
        cell = {"name": name, "c": c, "k": k}
        for sem in ("flip", "erasure"):
            for beta in (0.5, 0.9):
                cell[f"{sem}_{beta}"] = pmax(c, k, TABLE_N, TABLE_BUDGET,
                                             beta, sem)
        rows.append(cell)

    lines = [
        "# Forensic Tier Table (Tardos-fallback cells)",
        "",
        "Largest tolerable symbol-error rate `pmax` that still clears the "
        "courtroom tier, by region scale, under each p-semantics and detection "
        "power. These are the **Tardos-fallback** cells (coalition drift "
        "`(2/pi)*f(p)*sqrt(k)/c`), distinct from the Stage 0 c-independent "
        "single-source table in `stage0-soundness.md` (drift `d_tau=0.8627`).",
        "",
        f"Parameters: `n = {TABLE_N}`, courtroom `budget = {TABLE_BUDGET:.0e}` "
        "(Stage 0 ledger split of the 1e-6 courtroom allocation), "
        "`Qinv(budget/n)` in the inequality.",
        "",
        "`flip` factor `(1-2p)` is the hard-decision floor; `erasure` factor "
        "`(1-p)` applies only if unreadable symbols are truly dropped. `soft` "
        "(the production mode) has no scalar p-factor and is not tabulated here "
        "because pmax is p-independent by construction. `infeasible` = budget "
        "unreachable even at zero error.",
        "",
        "| Region scale | c | k | flip β=0.5 | flip β=0.9 | erasure β=0.5 | erasure β=0.9 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['c']} | {r['k']} | "
            f"{_fmt(r['flip_0.5'])} | {_fmt(r['flip_0.9'])} | "
            f"{_fmt(r['erasure_0.5'])} | {_fmt(r['erasure_0.9'])} |")
    lines.append("")
    return rows, "\n".join(lines)


if __name__ == "__main__":
    rows, md = build_table()
    print(f"Tardos-fallback pmax forensic table  "
          f"(n={TABLE_N}, budget={TABLE_BUDGET:.0e}):\n")
    for r in rows:
        print(f"{r['name']:24s} c={r['c']} k={r['k']:5d} | "
              f"flip:    b=0.5 pmax={_fmt(r['flip_0.5']):>10} "
              f"b=0.9 pmax={_fmt(r['flip_0.9']):>10}")
        print(f"{'':24s}         | "
              f"erasure: b=0.5 pmax={_fmt(r['erasure_0.5']):>10} "
              f"b=0.9 pmax={_fmt(r['erasure_0.9']):>10}")
    with open("forensic_table.md", "w", encoding="utf-8") as f:
        f.write(md + "\n")
    print("\nwrote forensic_table.md")
