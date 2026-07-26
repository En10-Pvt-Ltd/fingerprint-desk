#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stage 0 proven thresholds via numerical Chernoff bound.

Innocent per-symbol score U under the symmetric Tardos score, restricted to
the decoder-side bias window [tau, 1-tau]:
    p ~ arcsine restricted to [tau, 1-tau]
    U = +sqrt((1-p)/p)  with prob p
        -sqrt(p/(1-p))  with prob 1-p
(The distribution of U is the same whether the observed symbol y is 0 or 1,
and does not depend on how y was produced, so the attack never enters.)

Exact facts: E[U] = 0, E[U^2] = 1, |U| <= M = sqrt((1-tau)/tau).

Chernoff: ln P(S_k >= Z) <= inf_l>0 [ k K(l) - l Z ],  K(l) = ln E[e^{lU}].
We solve for the threshold Z* such that the bound equals ln(eta_0). This is
a PROVEN bound for every k, unlike the Gaussian approximation. Bernstein is
the closed-form fallback; Gaussian is shown for comparison only.

Also prints the feasibility table: max tolerable symbol flip rate p such that
the pure-source drift k_ret * d_tau * (1-2p) clears Z plus the detection-power
term z_beta * sqrt(k_ret).
"""
import numpy as np

TAU = 0.10
ETA0 = 2e-12                    # = (eps_stage0=5e-7) / (n=5000 * R_max=50)
LN_ETA = np.log(1.0 / ETA0)     # 26.94


def arcsine_window(tau, npts=20001):
    """Grid and normalized density of arcsine restricted to [tau, 1-tau]."""
    # Integrate in u where p = sin(pi u / 2)^2 maps U(0,1) to arcsine.
    u_lo = (2 / np.pi) * np.arcsin(np.sqrt(tau))
    u = np.linspace(u_lo, 1 - u_lo, npts)
    p = np.sin(np.pi * u / 2) ** 2
    w = np.gradient(u)                       # uniform in u = arcsine in p
    w /= w.sum()
    return p, w


P, W = arcsine_window(TAU)
A = np.sqrt((1 - P) / P)                     # positive score value
B = np.sqrt(P / (1 - P))                     # negative score magnitude
M = float(np.sqrt((1 - TAU) / TAU))
DRIFT = float(np.sum(W * 2 * np.sqrt(P * (1 - P))))   # d_tau per symbol
RETAIN = None  # set below vs full arcsine


def retain_fraction(tau):
    return 1 - 2 * (2 / np.pi) * np.arcsin(np.sqrt(tau))


RETAIN = retain_fraction(TAU)


LGRID = np.linspace(1e-4, 6.0, 2000)
KGRID = np.log(np.array([
    np.sum(W * (P * np.exp(l * A) + (1 - P) * np.exp(-l * B))) for l in LGRID]))


def K(l):
    return float(np.interp(l, LGRID, KGRID))


def rate(z_per_k):
    """Legendre transform I(z) = sup_l [l z - K(l)] per symbol."""
    return float(np.max(LGRID * z_per_k - KGRID))


def chernoff_Z(k, ln_eta=LN_ETA):
    lo, hi = 0.0, M * k          # S <= M k always
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if k * rate(mid / k) < ln_eta:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def bernstein_Z(k, ln_eta=LN_ETA):
    # Z^2 / (2 (k + M Z / 3)) = ln_eta
    a, b, c = 1.0, -2 * ln_eta * M / 3, -2 * ln_eta * k
    return (-b + np.sqrt(b * b - 4 * a * c)) / 2


def gauss_Z(k, ln_eta=LN_ETA):
    from math import erfc, sqrt
    lo, hi = 0.0, 12.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if 0.5 * erfc(mid / sqrt(2)) > np.exp(-ln_eta):
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi) * np.sqrt(k)


def p_max(k, Z, beta_term):
    """Max flip rate: k * DRIFT * (1-2p) >= Z + beta_term."""
    x = (Z + beta_term) / (k * DRIFT)
    return (1 - x) / 2 if x < 1 else float("nan")


if __name__ == "__main__":
    print(f"tau={TAU}  M={M:.3f}  drift/symbol d_tau={DRIFT:.4f}  "
          f"retain={RETAIN:.4f}  eta_0={ETA0:.1e}  ln(1/eta_0)={LN_ETA:.2f}\n")
    print(f"{'k_obs':>6} {'k_ret':>6} {'Z_gauss':>8} {'Z_chern':>8} "
          f"{'Z_bern':>8} {'pmax b=.5':>9} {'pmax b=.9':>9}")
    for k_obs in [200, 400, 1000, 2000, 8000]:
        k = int(round(k_obs * RETAIN))
        Zg, Zc, Zb = gauss_Z(k), chernoff_Z(k), bernstein_Z(k)
        pm5 = p_max(k, Zc, 0.0)
        pm9 = p_max(k, Zc, 1.2816 * np.sqrt(k))
        print(f"{k_obs:>6} {k:>6} {Zg:>8.1f} {Zc:>8.1f} {Zb:>8.1f} "
              f"{pm5:>9.3f} {pm9:>9.3f}")
    print("\npmax = NaN means infeasible even at zero symbol error: the "
          "proven threshold exceeds the maximum achievable pure-source drift.")
