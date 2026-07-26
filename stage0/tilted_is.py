#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Ground-truth tail estimation by exponentially tilted importance sampling.

Samples coordinates from the lambda-tilted distribution
    q_l(u) proportional to e^{l u} q(u)
at the Chernoff-optimal lambda* for the target threshold, and reweights:
    P(S >= Z) = E_tilt[ 1{S >= Z} exp(-l S + k K(l)) ].
Unbiased, with relative error a few percent at 1e6 samples even at the
1e-12 tail. This is the reference against which AMS is validated; AMS
remains the general-purpose tool when the score is not a sum of iid terms
(soft weights, region dependence), where tilting is not available in
closed form.
"""
import numpy as np
import chernoff as ch


def tilted_tail(k, Z, n=1_000_000, seed=0, chunks=10):
    # Optimal lambda from the precomputed CGF grid.
    j = int(np.argmax(ch.LGRID * (Z / k) - ch.KGRID))
    lam, Kl = float(ch.LGRID[j]), float(ch.KGRID[j])
    # Tilted joint distribution over the p-grid and B.
    wpos = ch.W * ch.P * np.exp(lam * ch.A)          # B = 1 branch
    wneg = ch.W * (1 - ch.P) * np.exp(-lam * ch.B)   # B = 0 branch
    zsum = wpos.sum() + wneg.sum()                    # = e^{K(lam)}
    probs = np.concatenate([wpos, wneg]) / zsum
    vals = np.concatenate([ch.A, -ch.B])
    rng = np.random.default_rng(seed)
    est, est2, m = 0.0, 0.0, 0
    for _ in range(chunks):
        nn = n // chunks
        idx = rng.choice(len(vals), size=(nn, k), p=probs)
        S = vals[idx].sum(axis=1)
        wgt = np.where(S >= Z, np.exp(-lam * S + k * np.log(zsum)), 0.0)
        est += wgt.sum(); est2 += (wgt ** 2).sum(); m += nn
    mean = est / m
    se = np.sqrt(max(est2 / m - mean ** 2, 0) / m)
    return mean, se, lam


if __name__ == "__main__":
    import sys
    k_obs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    Z = float(sys.argv[2]) if len(sys.argv) > 2 else 79.4
    k = int(round(k_obs * ch.RETAIN))
    mean, se, lam = tilted_tail(k, Z)
    print(f"k_obs={k_obs} k_ret={k} Z={Z} lambda*={lam:.3f}")
    print(f"P(S >= Z) = {mean:.3e} +/- {se:.1e}  "
          f"(Chernoff bound at this Z: {np.exp(-k*ch.rate(Z/k)):.3e})")
