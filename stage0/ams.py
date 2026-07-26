#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Adaptive multilevel splitting (AMS) validation of the Stage 0 tail.

Estimates P(S_k >= Z) for the innocent Stage 0 score at probabilities far
below direct Monte Carlo reach (target eta_0 = 2e-12, ~7 sigma; 1e6 direct
trials only probe ~4.75 sigma). Lineage: Cerou, Furon, Guyader, adaptive
multilevel splitting for static rare events, as used to estimate minimal
Tardos code lengths.

State: N particles, each a vector of k iid coordinates (p_i, B_i) with
p ~ arcsine restricted to [tau, 1-tau], B ~ Bern(p),
U_i = +sqrt((1-p_i)/p_i) if B_i else -sqrt(p_i/(1-p_i)),  S = sum U_i.
The innocent score distribution does not depend on the leaked bits y or on
the attack, so this simulates the EXACT innocent distribution.

Fixed-ratio AMS: kill the worst KILL fraction per level, resample from
survivors, decorrelate with Metropolis moves that refresh a few random
coordinates from the prior and accept iff S stays above the level
(independence proposal times indicator target, exact acceptance rule).
Cumulative estimate after j levels: (1-KILL)^j times the surviving fraction.

Outputs the estimated Z at eta_0 (level where cumulative prob crosses 2e-12)
and the estimated tail at the Chernoff threshold, over 3 independent seeds.
"""
import numpy as np

TAU = 0.10
ETA0 = 2e-12
KILL = 0.20
N = 1000
MOVES = 40            # Metropolis sweeps per level
REFRESH = 6           # coordinates refreshed per move

U_LO = (2 / np.pi) * np.arcsin(np.sqrt(TAU))


def sample_coords(rng, shape):
    u = rng.uniform(U_LO, 1 - U_LO, size=shape)
    p = np.sin(np.pi * u / 2) ** 2
    B = rng.random(shape) < p
    U = np.where(B, np.sqrt((1 - p) / p), -np.sqrt(p / (1 - p)))
    return U


def ams_tail(k, z_targets, seed):
    rng = np.random.default_rng(seed)
    U = sample_coords(rng, (N, k))
    S = U.sum(axis=1)
    logp = 0.0                              # log of cumulative probability
    curve = []                              # (level, log10 cum prob)
    for level_idx in range(400):
        q = np.quantile(S, KILL)
        if q >= S.max():
            break
        dead = S <= q
        surv_frac = float((~dead).mean())
        if surv_frac == 0.0:
            break
        logp += np.log(surv_frac)   # empirical fraction, NOT nominal 1-KILL:
        # with duplicated particles, ties at the quantile kill more than the
        # nominal fraction, and crediting 1-KILL biases the estimate upward.
        survivors = np.where(~dead)[0]
        # Resample dead particles from survivors.
        src = rng.choice(survivors, size=dead.sum())
        U[dead] = U[src]
        S[dead] = S[src]
        # Metropolis decorrelation for ALL particles above level q.
        for _ in range(MOVES):
            # Sample refresh coordinates WITHOUT replacement per particle:
            # duplicate indices would corrupt the delta update (two writes to
            # one coordinate, last wins, while delta assumed two coordinates).
            idx = np.argsort(rng.random((N, k)), axis=1)[:, :REFRESH]
            newU = sample_coords(rng, (N, REFRESH))
            rows = np.arange(N)[:, None]
            delta = newU.sum(axis=1) - U[rows, idx].sum(axis=1)
            accept = (S + delta) > q
            U[rows[accept], idx[accept]] = newU[accept]
            S[accept] += delta[accept]
        S = U.sum(axis=1)      # kill any accumulated floating-point drift
        curve.append((float(q), logp / np.log(10)))
        if logp < np.log(ETA0) - 4:         # go a bit past the target
            break
    curve = np.array(curve)
    # Z at eta_0 by interpolation on the (level, log10 p) curve.
    lp = np.log10(ETA0)
    z_at_eta = float(np.interp(-lp, -curve[:, 1], curve[:, 0]))
    # Tail estimates at requested thresholds.
    tails = [10 ** float(np.interp(z, curve[:, 0], curve[:, 1]))
             for z in z_targets]
    return z_at_eta, tails


if __name__ == "__main__":
    import sys
    k_obs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    z_chern = float(sys.argv[2]) if len(sys.argv) > 2 else 79.4
    retain = 1 - 2 * (2 / np.pi) * np.arcsin(np.sqrt(TAU))
    k = int(round(k_obs * retain))
    print(f"AMS: k_obs={k_obs} k_ret={k} tau={TAU} N={N} kill={KILL} "
          f"targets: eta_0={ETA0:.0e}, Z_chern={z_chern}")
    for seed in (1, 2, 3):
        z_eta, tails = ams_tail(k, [z_chern], seed)
        print(f"  seed {seed}: Z(eta_0) = {z_eta:.1f}   "
              f"P(S >= Z_chern) = {tails[0]:.2e}")
