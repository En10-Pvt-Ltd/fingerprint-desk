#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Locked-number tests for metrics.py. Plain asserts, no framework.

Run: python test_metrics.py

These lock the corrected p-semantics fix: the courtroom cell pmax under flip
(the hard-decision floor) is about half the old erasure-calibrated value, and
soft mode ignores p entirely.
"""
from metrics import Q, Qinv, epsilon1, pmax

PASS = 0


def approx(got, want, tol, label):
    global PASS
    assert abs(got - want) <= tol, f"{label}: got {got:.6f}, want {want} (tol {tol})"
    PASS += 1
    print(f"  ok  {label}: {got:.6f} ~= {want} (tol {tol})")


def check(cond, label):
    global PASS
    assert cond, f"{label}: FAILED"
    PASS += 1
    print(f"  ok  {label}")


# Courtroom cell, Stage 0 ledger split.
C, K, N, BUDGET = 5, 8000, 5000, 5e-7

print("courtroom cell c=5, k=8000, n=5000, budget=5e-7")
approx(pmax(C, K, N, BUDGET, 0.5, "flip"), 0.221, 0.005, "flip pmax beta=0.5")
approx(pmax(C, K, N, BUDGET, 0.9, "flip"), 0.164, 0.005, "flip pmax beta=0.9")
approx(pmax(C, K, N, BUDGET, 0.5, "erasure"), 0.441, 0.005, "erasure pmax beta=0.5")
approx(pmax(C, K, N, BUDGET, 0.9, "erasure"), 0.329, 0.005, "erasure pmax beta=0.9")

print("flip semantics with p >= 0.5 is unattributable")
check(epsilon1(C, K, 0.5, N, "flip") == 1.0, "epsilon1 flip p=0.5 == 1.0")
check(epsilon1(C, K, 0.7, N, "flip") == 1.0, "epsilon1 flip p=0.7 == 1.0")

print("soft mode ignores p entirely")
check(epsilon1(C, K, 0.0, N, "soft") == epsilon1(C, K, 0.9, N, "soft"),
      "epsilon1 soft p=0.0 == epsilon1 soft p=0.9")

print("Qinv round-trips: Q(Qinv(x)) ~= x")
for x in (1e-6, 1e-10, 2e-12):
    approx(Q(Qinv(x)), x, 1e-3 * x, f"Q(Qinv({x:.0e}))")

print(f"\nALL {PASS} CHECKS PASSED")
