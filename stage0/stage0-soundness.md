# Stage 0 Soundness: False-Accusation Guarantees for the Purity-Collapse Decoder
## Spec v0.4 module. Closes the hole identified after v0.3.

Status of the numbers: every threshold and feasibility figure in this document was computed and cross-validated in-session by three independent methods (numerical Chernoff bound, exponentially tilted importance sampling, adaptive multilevel splitting), shipped as runnable code in stage0/. Nothing below rests on the Gaussian approximation.

Assumptions stated inline: fresh codewords per exam with no reuse across exams or sessions, secret codebook, budget split epsilon_1 = 1e-6 into 5e-7 for the Stage 0 path and 5e-7 for the Tardos fallback path, region count cap R_max = 50 (question granularity on a 12-page paper) with the adaptive alternative given in 3.2, decoder-side bias window tau = 0.10, hard-decision decoding with erasures for the proven path.

---

## 1. The Stage 0 accusation statistic and its threshold (Deliverable 1)

### 1.1 Statistic

For a leaked region with observed positions K, the Stage 0 score of copy j is the symmetric Tardos score restricted to K and to the decoder-side bias window:

S_j(K) = sum over i in K_ret of U(y_i, X_ji, p_i),
K_ret = { i in K : tau <= p_i <= 1 - tau, symbol i not erased },

with the standard symmetric score U (match at position i scores +sqrt((1-p_i)/p_i) or +sqrt(p_i/(1-p_i)) depending on the bit, mismatch scores the negative counterpart). Erasure decisions may depend only on channel quality of y, never on any codeword. tau = 0.10 gives |U| <= M = 3, retains a fraction 0.5903 of positions, and raises the pure-source drift per retained symbol to d_tau = 0.8627 (the arcsine mass near 0 and 1 contributes almost no drift but unbounded score range, so windowing is nearly free in drift and decisive for tail control).

The window is a decoder-side choice. The code is generated with the standard small Tardos cutoff, unchanged, so the Tardos fallback path is untouched.

### 1.2 Threshold, set from the innocent distribution alone

Accuse copy j from region K iff S_j(K) > Z(k_ret), where Z(k_ret) is set so that P(S_innocent > Z) <= eta_0, with eta_0 the per-(copy, region) budget from the ledger in Section 3. Two flavors, both constructed from the innocent-codeword distribution only, mirroring the Tardos construction:

- Z_proven(k_ret): the numerical Chernoff threshold. ln P(S >= Z) <= inf over lambda of [k_ret K(lambda) - lambda Z] with K the exact cumulant generating function of U (a one-dimensional integral over the windowed arcsine). This is a proven bound for every k_ret, no asymptotics. Bernstein with M = 3 is the closed-form fallback, strictly looser.
- Z_validated(k_ret): the exact tail quantile, certified numerically by tilted importance sampling and AMS (Section 5). Tighter by about 4 score points at question scale. Epistemic status: exact-distribution numerical certificate, not a closed-form proof.

Operational rule: courtroom accusations use Z_proven. The gap to Z_validated costs about 5 retained symbols of drift and buys unconditional status. Z_validated is reported as confirmation.

Design rule, non-negotiable: the purity test never modifies the threshold, the budget, or the window. It gates only whether a region's Stage 0 result is REPORTED with a purity annotation, and gating can only reduce accusations (Section 3.3).

---

## 2. The attack-agnostic innocence lemma (Deliverable 3, resolved by construction)

**Lemma.** Let j be a copy whose codeword X_j is independent of the leaked symbols y given the bias vector (guaranteed when codewords are fresh per exam, never reused, and the codebook is secret). Then conditional on the biases and on y, however y was produced, the terms U(y_i, X_ji, p_i) for i in K_ret are independent with E[U_i] = 0, E[U_i^2] = 1 exactly, and |U_i| <= M. Consequently every bound in Section 1.2 holds uniformly over all attacks: pure regions, spliced regions, marking-assumption mixtures, scan-and-composite output, adversarially chosen bits, and in particular impure regions misclassified as pure by any purity test.

Proof. Given p_i, the innocent bit X_ji is Bernoulli(p_i) independent of y_i. Direct computation gives, for either value of y_i, E[U_i] = sqrt(p_i(1-p_i)) - sqrt(p_i(1-p_i)) = 0 and E[U_i^2] = (1-p_i) + p_i = 1. Independence across i holds because innocent bits are independent across positions given biases. The Chernoff bound then applies conditionally on any realization of y, hence uniformly over the adversary's strategy. QED.

A corollary worth stating because it dissolves the feared compounding: the distribution of U_i for an innocent copy does not depend on y_i at all (the two cases y = 0 and y = 1 give the same law after the p to 1-p symmetry of the arcsine). The innocent score distribution is therefore universal, one distribution per k_ret, which is what makes precomputed thresholds and offline rare-event validation possible.

Labeling. PROVEN under the stated independence condition. If codewords are reused across sessions, or the adversary has previously observed a leak of the innocent copy's codeword under the same codebook, independence fails and nothing here applies; that regime is out of scope and operationally forbidden (fresh codes per exam are already required by the key-management design). The prompt's danger scenario, an A+B splice misclassified as pure that then convicts innocent C, is covered by the lemma: C's score statistics are identical whether the region is pure, spliced, or arbitrary, so the misclassification never touches C's false-accusation probability. What the 3/4 agreement structure of shared-bias codewords actually degrades is DETECTION of A and B (their drift on a spliced region is roughly halved each), never innocent soundness.

---

## 3. End-to-end union bound (Deliverable 2)

### 3.1 The compound structure dissolves

The feared bound was P(purity false-accept) x P(misattribution | false-accept). It is unnecessary. Accusation of innocent j via region r requires the event {gate passes for r} AND {S_j(r) > Z(k_ret,r)}, and

P(gate AND S_j > Z) <= P(S_j > Z) <= eta_0,

by the lemma, regardless of how correlated the gate is with anything. The purity test appears nowhere in the soundness accounting. For completeness the conservative compound inequality is P(gate AND S > Z) <= min(P(gate), P(S > Z)), dominated by the second factor alone.

### 3.2 The ledger, explicit

Total budget epsilon_1 = 1e-6 per exam, split 5e-7 Stage 0, 5e-7 Tardos fallback (both paths run on the same evidence, so they union).

Stage 0: P(any innocent copy accused by any region)
<= sum over regions r <= R, copies j <= n of P(S_j(r) > Z(k_ret,r))
<= n R eta_0.

Fixed allocation used for all worked numbers: n = 5000, R_max = 50, eta_0 = 5e-7 / (5000 x 50) = 2e-12, ln(1/eta_0) = 26.94. Adaptive alternative: set eta_0 = 5e-7 / (n R_obs) after counting the actually tested regions R_obs; valid because thresholds are computed per case before scoring, and strictly tighter when leaks contain few regions. An adversary who fragments the leak into many tiny regions buys more accusation attempts but each carries a proportionally smaller budget; the union bound is airtight either way.

Tardos fallback: rerun of the v0.2 threshold at 5e-7 instead of 1e-6 moves the Gaussian point from Qinv(2e-10) = 6.25 to Qinv(1e-10) = 6.36, a trivial tightening propagated to the cells.

Multiplicity notes. Thresholds depend on the observed k_ret,r, which is leak-determined; the bound is conditional on k_ret,r and remains valid. Cross-region aggregation (summing a copy's scores over regions) is exactly the global Tardos score restricted to observed positions and is charged to the Tardos half of the ledger, not to Stage 0.

### 3.3 What the purity test is for, restated

Detection power and semantics only. A region passing purity yields the strong per-region claim "this region's content matches copy A at pure-source drift, attribution is c-independent." A region failing purity falls through to the Tardos fallback. The accusation sentence in a report must be "copy j's region score exceeded a threshold calibrated so that an uninvolved copy crosses with probability at most eta_0," never "the region was pure, therefore j." Purity is descriptive annotation, never load-bearing for soundness.

---

## 4. Worked constants (computed, not estimated)

Parameters: tau = 0.10, M = 3, retain = 0.5903, drift d_tau = 0.8627 per retained symbol, eta_0 = 2e-12. Pure-source drift at hard-decision flip rate p: k_ret x 0.8627 x (1 - 2p). Detection power beta uses the guilty-side Gaussian with variance <= k_ret (E[U^2] = 1 exactly), acceptable because power is not a soundness quantity. pmax is the largest flip rate at which the drift clears Z_proven plus the power term z_beta sqrt(k_ret).

| Region scale | k_obs | k_ret | Z_gauss | Z_proven (Chernoff) | Z_bernstein | pmax, beta=0.5 | pmax, beta=0.9 |
|---|---|---|---|---|---|---|---|
| Single question | 200 | 118 | 75.4 | 79.4 | 111.1 | 0.110 | 0.042 |
| Two questions | 400 | 236 | 106.6 | 112.5 | 142.9 | 0.224 | 0.175 |
| Single page | 1000 | 590 | 168.5 | 178.1 | 207.2 | 0.325 | 0.294 |
| Two pages | 2000 | 1181 | 238.4 | 252.1 | 280.6 | 0.376 | 0.355 |
| Full paper | 8000 | 4723 | 476.8 | 504.4 | 532.1 | 0.438 | 0.427 |

All rows are c-independent: this is the purity collapse paying off. For comparison the Tardos fallback at question scale offers nothing at any c, and at page scale offers c = 2 at a far weaker epsilon_1.

**Correction flag, propagates to v0.2 and v0.3 cells.** The master inequality used the factor (1 - p). That factor is correct only for an ERASURE channel (unreadable symbols dropped). For a hard-decision FLIP channel the drift factor is (1 - 2p): a match contributes +2 sqrt(p_i(1-p_i)) in expectation, a flip contributes the same magnitude negative, so errors cost double. All Stage 0 numbers above already use (1 - 2p). The Tardos-path cells must be recomputed with (1 - 2p) under flip semantics, or the decoder must be run in erasure mode (declare low-|LLR| symbols erasures, shrink k, keep retained error small), which restores near-linear cost and is the recommended operating mode. Corrected Tardos courtroom cell (c = 5, k = 8000, n = 5000, budget 5e-7): flip tolerance p <= 0.221 at beta = 0.5 and p <= 0.164 at beta = 0.9, versus the previously tabulated 0.45 and 0.34. harness/metrics.py needs the one-line factor change and an explicit p-semantics field. This correction also retroactively invalidates the v0.2 single-question courtroom cell on a second ground: it was computed from the Gaussian tail WITHOUT a bias window, where |U| can reach sqrt(300c) and the Gaussian at k = 200 is untrustworthy. The window plus Chernoff treatment above is the sound replacement.

---

## 5. Rare-event validation at the 1e-12 tail (Deliverable 4)

Direct Monte Carlo cannot certify eta_0 = 2e-12 (about 7 sigma; 1e6 trials probe 4.75 sigma). Shipped machinery, all in stage0/:

1. **chernoff.py.** Exact CGF of the windowed innocent score by one-dimensional integration, Legendre transform on a lambda grid, bisection for Z_proven. Cross-checked against direct MC at reachable levels (z = 30, 40, 50 for k_ret = 118): the bound upper-bounds the empirical tail at every level with the expected polynomial-prefactor slack of roughly 10x.
2. **tilted_is.py.** Exponentially tilted importance sampling at the Chernoff-optimal lambda*, unbiased, relative error a few percent at 1e6 samples even at 1e-13. Gold standard for the iid hard-decision score. Measured, k_ret = 118: P(S >= 79.4) = 1.067e-13 +/- 3.1e-16, a factor 19 inside the Chernoff guarantee of 2e-12.
3. **ams.py.** Adaptive multilevel splitting (Cerou, Furon, Guyader lineage), the general-purpose tool for score variants where closed-form tilting is unavailable (soft LLR weights, per-region weighting, fused carriers). Fixed-ratio kill at 20 percent, prior-refresh Metropolis moves accepted iff the score stays above the level, empirical surviving fraction (not the nominal 1 - kill) in the estimator. Measured after calibration, k_ret = 118, three seeds: P(S >= 79.4) = 1.16e-13 to 1.19e-13 against the tilted-IS truth of 1.07e-13, and empirical Z(eta_0) = 75.0 to 75.3 against Gaussian 75.4.

Calibration protocol, mandatory and paper-worthy: AMS must reproduce the tilted-IS answer on the iid case before being trusted on any non-tiltable variant. This session demonstrated why. Two AMS bugs were found and fixed against the reference: crediting the nominal survivor fraction when duplicate particles tie at the kill quantile, and, far worse, refresh coordinates drawn with replacement so that duplicate indices within one move corrupted the delta update of the score, an error that accumulates and inflated the tail estimate by orders of magnitude. An uncalibrated rare-event sampler is a random-number generator with confidence.

Validation verdict: at tau = 0.10 the exact 2e-12 quantile sits essentially at the Gaussian point (75.3 vs 75.4 at k_ret = 118), because the window bounds |U| <= 3 and moderate-deviation Gaussian behavior holds. The proven Chernoff threshold costs 4 score points over exact. Both are affordable; use proven.

---

## 6. Verdict and the honest failure mode, once (Deliverable 5)

What the math supports: Stage 0 is a courtroom-grade accusation path at every fragment scale, under proven thresholds, c-independent, with the false-accusation side unconditional on purity, attacks, and mixtures (Lemma, Section 2). The compound purity-times-attribution failure the prompt feared does not exist, because innocent scores are attack-agnostic by construction. Stage 0 does NOT downgrade to investigative-lead status. The Tardos path remains the fallback for impure regions and the safety net, with its cells corrected per Section 4.

The honest cost, stated once. The guarantee is bought with tight noise budgets at small scales and the standing power caveat. At single-question scale the proven-threshold flip-rate budget is 11 percent at 50 percent detection power and 4 percent at 90 percent power, post-fusion, hard-decision. If the real channel (bad phone, WhatsApp, cleanup pass) cannot deliver question-scale symbol error at or below roughly 10 percent, question-scale accusations fail to fire and the practical tier for tiny fragments reverts to investigative lead, not because soundness broke but because detection starved. Whether the channel clears that bar is exactly what the leak-corpus harness measures, and the (1 - 2p) correction means the corrected Tardos cells are tighter than previously advertised too, full-paper flip tolerance 22 percent, not 45. Detection power at the tabulated pmax is 50 percent by construction, never falsely accuse, sometimes fail to attribute, and raising power to 90 percent costs the difference between the two pmax columns. All of this is measurable, none of it is hidden, and the false-accusation axis, the political kill-shot, is now closed with proofs and two independent numerical certificates.
