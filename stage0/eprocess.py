#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Anytime-valid sequential accusation via a mixture e-process (v0.5 core).

Problem this solves that fixed-length Tardos cannot. A leaker drips fragments
over days or weeks. Each new fragment adds observed symbols to a copy's score.
A fixed-threshold test that is re-checked after every drip suffers multiple-
testing inflation: the union bound over an unknown, growing number of looks
destroys the 1e-6 budget. Classical Tardos has no valid stopping rule.

Solution. Build a nonnegative mixture e-process E_j(t) for each copy j whose
expectation under innocence is at most 1 at every stopping time. By Ville's
inequality, P(sup_t E_j(t) >= 1/alpha) <= alpha for the WHOLE infinite drip,
no matter when or how often we look. Accuse when E_j >= 1/alpha. This is a
sequential, always-valid version of the Stage 0 accusation, and it is what
makes drip-leak attribution rigorous.

Construction. Per retained symbol i, innocent increment U_i has the exact
mean-0, variance-1, bounded law of the windowed symmetric Tardos score
(proven attack-agnostic lemma, stage0-soundness.md Section 2). For each tilt
lambda, exp(lambda sum U_i - t_ret psi(lambda)) is a nonnegative
supermartingale under innocence, where psi(lambda) = ln E_innocent[e^{lambda U}]
is the exact CGF. Mixing over lambda with a prior w(lambda) keeps it a
supermartingale (average of supermartingales), and adapts to the unknown
guilty drift so we need not tune lambda. E_j(t) = sum_l w_l exp(lambda_l S_j -
t_ret psi(lambda_l)).

Guarantees:
  PROVEN. Innocent: E[E_j(tau)] <= 1 at any stopping time tau, so
    P(ever accuse innocent j) <= alpha (Ville). Union over n copies: set
    alpha = epsilon_1 / n. Attack-agnostic, holds against any splice, any
    look schedule, any drip pattern, because the innocent increment law does
    not depend on the leaked bits.
  MEASURED (this file). Guilty pure-source drip at 10 percent flip:
    100 percent detected, median 143 retained symbols to cross, roughly one
    to two exam questions.
"""
import numpy as np

TAU = 0.10
U_LO = (2 / np.pi) * np.arcsin(np.sqrt(TAU))

# Exact innocent CGF psi(lambda) on a grid (windowed arcsine score).
_P, _W = None, None


def _arcsine_window(npts=20001):
    u = np.linspace(U_LO, 1 - U_LO, npts)
    p = np.sin(np.pi * u / 2) ** 2
    w = np.gradient(u); w /= w.sum()
    return p, w


_P, _W = _arcsine_window()
_A = np.sqrt((1 - _P) / _P)
_B = np.sqrt(_P / (1 - _P))
LAMS = np.linspace(0.05, 1.20, 24)
PSI = np.array([np.log(np.sum(_W * (_P * np.exp(l * _A) + (1 - _P) * np.exp(-l * _B))))
                for l in LAMS])
PRIOR = np.exp(-0.5 * (LAMS / 0.5) ** 2); PRIOR /= PRIOR.sum()


class EProcess:
    """One always-valid accusation accumulator for a single copy j."""

    def __init__(self, alpha):
        self.alpha = alpha
        self.cum = np.zeros(len(LAMS))     # per-tilt log accumulator
        self.peak = 0.0

    def update(self, U_increments):
        """Feed newly observed retained-symbol scores for copy j (any batch)."""
        for u in np.atleast_1d(U_increments):
            self.cum += LAMS * u - PSI
            E = float(np.dot(PRIOR, np.exp(self.cum)))
            self.peak = max(self.peak, E)
        return self.evalue()

    def evalue(self):
        return float(np.dot(PRIOR, np.exp(self.cum)))

    def accuse(self):
        return self.evalue() >= 1.0 / self.alpha


def sample_innocent(n, k, rng):
    u = rng.uniform(U_LO, 1 - U_LO, size=(n, k)); p = np.sin(np.pi * u / 2) ** 2
    B = rng.random((n, k)) < p
    return np.where(B, np.sqrt((1 - p) / p), -np.sqrt(p / (1 - p)))


def sample_guilty(n, k, rng, flip=0.10):
    u = rng.uniform(U_LO, 1 - U_LO, size=(n, k)); p = np.sin(np.pi * u / 2) ** 2
    Xj = rng.random((n, k)) < p
    y = Xj.copy(); fl = rng.random((n, k)) < flip; y = np.where(fl, ~y, y)
    match = (y == Xj)
    return np.where(match,
                    np.where(Xj, np.sqrt((1 - p) / p), np.sqrt(p / (1 - p))),
                    np.where(Xj, -np.sqrt(p / (1 - p)), -np.sqrt((1 - p) / p)))


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    n, alpha = 5000, 2e-12
    Ui = sample_innocent(200000, 300, rng)
    cum = np.zeros((Ui.shape[0], len(LAMS))); peak = np.zeros(Ui.shape[0])
    for i in range(Ui.shape[1]):
        cum += LAMS[None, :] * Ui[:, i][:, None] - PSI[None, :]
        peak = np.maximum(peak, (PRIOR[None, :] * np.exp(cum)).sum(axis=1))
    print(f"Innocent over 2e5 drips of k=300, alpha=eps1/n={alpha:.0e}:")
    print(f"  ever-cross rate at 1/alpha: {(peak >= 1/alpha).mean():.2e} "
          f"(Ville guarantees <= alpha); max e-value {peak.max():.2e}")

    Ug = sample_guilty(20000, 400, rng, flip=0.10)
    cum = np.zeros((Ug.shape[0], len(LAMS))); crossed = np.full(Ug.shape[0], -1)
    for i in range(Ug.shape[1]):
        cum += LAMS[None, :] * Ug[:, i][:, None] - PSI[None, :]
        E = (PRIOR[None, :] * np.exp(cum)).sum(axis=1)
        nc = (crossed < 0) & (E >= 1/alpha); crossed[nc] = i + 1
    det = crossed > 0
    print(f"Guilty pure drip, flip=0.10: detected {det.mean()*100:.1f}%, "
          f"median symbols to accuse {np.median(crossed[det]):.0f}")
