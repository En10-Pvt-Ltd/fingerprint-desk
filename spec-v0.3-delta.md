# Spec v0.3, Revision Delta over v0.2

Scope: this document contains the rewritten Section 1, the Section 2 update, the Section 3.2 rotation addition, the Section 5 verification flag, and the build spec. Everything else in v0.2 stands unchanged (mission, strategic shape, NEET reference case, threat model, non-goals, symmetric Tardos at 8,192, soft-LLR fusion, dual-carrier stack, analytic threshold plus AMS tail validation).

Runnable code shipped with this revision: smoke_test/ (encoder, synthetic channel, blind decoder, all container-verified end to end) and harness/ (metrics with the analytic tier lookup, channel multipliers, bakeoff skeleton).

---

## Section 1, rewritten: The Position-Blind Print Colluder

### 1.1 Retraction and the corrected axis

v0.2 claimed print selection is "a strict subset of the Boneh-Shaw marking-assumption attack class." RETRACTED, the claim is false for a binary alphabet. At any detectable position the colluders jointly hold both a 0 and a 1, so "output some colluder's symbol" means "output any bit," which is exactly the marking adversary's full power. Binary has no intermediate values to forgo, so the selection-versus-averaging distinction is vacuous at the symbol layer. Position-AWARE selection EQUALS the marking adversary.

The genuine source of weakness in the print colluder is POSITION-BLINDNESS. The print colluder cannot see where symbols are embedded, so cannot exercise per-symbol control. They can only route at page or region granularity: this page from copy A, that crop from copy B. Routing at region granularity locks every symbol inside a chosen region to a single copy, including at detectable positions where a marking adversary would want to switch. That coarseness, not selection-ness, is what makes the realizable print colluder strictly weaker.

### 1.2 Two layers, cleanly separated (v0.2 conflated them)

- **Pixel/carrier layer.** Physical-signal averaging (scan-average-reprint, operation 3 in the v0.2 taxonomy) attenuates the physical mark itself. It requires a flatbed scanner, pixel registration, and a reprint, exactly the workflow whose absence defines the quick-photo leak this system targets. This layer is about mark survivability, not code security.
- **Symbol/code layer.** The collusion-code question. Here the realizable weakness is purely the coarse-grained, position-blind region routing described above, and it is analyzed against the code, independent of how symbols are physically carried.

All code-length claims below live at the symbol/code layer.

### 1.3 Formal adversary: the position-blind region-routing channel

Setup. m embedded symbol positions per copy, secret spatial mapping sigma from positions to page locations. The colluder holds c copies, partitions the leaked artifact into R regions (pages, questions, crops; R << m, for the NEET layout R <= 12 pages or roughly 50 questions against m = 8,192, so hundreds of symbols per region), and chooses a routing a: region -> copy. The output symbol at position i is X_{a(r(i)), i} where r(i) is the region containing sigma(i). Constraints that define the channel:

1. Position-blind: routing may depend on visible content but not on symbol positions or values (no knowledge of sigma, no pixel registration).
2. Region-pure: every symbol inside a region comes from the single routed copy.
3. R routing choices total, not m per-symbol choices.

Consequence, the purity collapse. Within any leaked region, the observed symbols are a noisy read of exactly one codeword. Decoding a pure region is not a collusion problem at all, it is single-source identification among n codewords, which needs on the order of ln(n/eta) / D(p) symbols, where D(p) is the per-symbol discrimination exponent of the noisy channel. That is tens to low hundreds of symbols, independent of c, versus the Tardos requirement of order c^2 ln(n/eta). Each routed region separately convicts the copy it came from, and every colluder who supplied at least one photographed region is attributed.

### 1.4 Claims versus conjecture (labeling discipline retained)

- PROVEN (classical). Tardos codes resist the full marking-assumption adversary, hence also every position-blind colluder, at m = O(c^2 ln(n/eta)). This is the unconditional safety net and it is not weakened by anything below.
- PROVEN (standard hypothesis testing). If a leaked region is pure (assumption 2 holds for it), single-source identification within that region succeeds with error probability at most eta using k_region = O(ln(n/eta)) observed symbols, with the constant set by the channel's discrimination exponent at error rate p. No collusion penalty applies inside a pure region.
- PROVEN (containment direction only). The position-blind region-routing adversary is strictly contained in the marking adversary whenever R < m and at least one region spans two or more detectable positions, because the router is forced to correlate outputs across positions that the marking adversary could set independently.
- CONJECTURE, the open theorem for the paper. For the position-blind region-routing channel with R regions, there is a two-stage decoder (per-region purity test and single-source attribution, falling back to the Tardos score on impure regions) whose required total observed symbols scale as O(R + ln(n/eta)) up to channel constants, independent of c, strictly below the c^2 scaling, with a phase transition: as the adversary shrinks regions toward symbol granularity (R -> m), which is physically unrealizable without pixel-level compositing, the bound continuously degrades to classical Tardos. The containment is proven; the quantitative bound and the location of the phase transition are to be derived or empirically supported by the benchmark.
- IMPLEMENTATION COROLLARY (follows from the proven parts). The forensic decoder should be two-stage in practice: Stage 0 runs a per-region purity statistic (fraction of decoded symbols in the region matching the best-fit codeword); regions passing purity get c-independent single-source attribution; only impure regions fall through to the Tardos accusation score. Stage 0 is where the realizable adversary actually lands, Tardos is the floor for everything else.

---

## Section 2, updated: Cells Are Interleaving-Calibrated Placeholders, and the Power Statement

### 2.1 What the cells silently assumed

Every (c, k, p) cell in v0.2 uses the guilty drift mu_g = k (1-p) (2/pi) / c, which is the drift under the INTERLEAVING attack. Interleaving is asymptotically the worst case for the joint decoder at large c, but c = 2 and c = 5 are not asymptotically large, and at small c other marking-assumption attacks (majority and minority voting among them) can degrade drift more than interleaving (Furon and Perez-Freire, arXiv 0903.3480, already cited in Section 1.3 of v0.2 but not propagated into the cells). The cells are therefore interleaving-calibrated placeholders, with corrections pulling in both directions:

- **Upward pressure on required length (cells optimistic).** Against the general marking-assumption worst case at small c, the true drift is lower than the interleaving drift, so the real epsilon_1 at a given (c, k, p) is worse than tabulated.
- **Downward pressure (cells conservative).** The physically realizable position-blind region-routing colluder of Section 1 is strictly weaker than interleaving at the symbol level: it cannot even mix within a region. Under Stage 0 purity decoding, realizable-adversary performance is far better than any cell suggests.

The net is empirical. The leak-corpus benchmark plus a drift derivation for the position-blind channel fix the true constant. Sections 1 and 2 are now the same model: the cells bound the marking-adversary floor (up to the small-c interleaving caveat), Stage 0 captures the realizable ceiling.

### 2.2 The 50-percent-power statement (explicit, was silent)

Every cell sets mu_g = Z, the point where the average colluder's expected score equals the threshold. At that operating point detection power is 50 percent: half the time the average colluder is NOT attributed. The false-accusation side (epsilon_1) is rigorous regardless, because the threshold is set from the innocent distribution alone. The asymmetry is defensible for a forensic tool, never falsely accuse, sometimes fail to attribute, but it must be stated in every tier definition, and it now is.

Cost to raise power to beta: require mu_g >= Z + z_beta sqrt(k), with z_beta = Qinv(1 - beta) (z_0.9 = 1.28, z_0.95 = 1.64). The master inequality becomes

(2/pi) (1-p) sqrt(k) / c  >=  Qinv(epsilon_1 / n) + Qinv(1 - beta).

Worked consequence for the courtroom tier (full paper, c = 5, k = 8,000, n = 5,000, epsilon_1 = 1e-6): at beta = 0.5 the tier tolerates effective p up to about 0.45; at beta = 0.9 the tolerance drops to p <= 0.34. Container-verified from harness/metrics.py: the p = 0.45 cell that reads 9.4e-7 (courtroom) at beta = 0.5 reads 1.6e-3 (weak lead) at beta = 0.9, while the p = 0.20 cell stays courtroom at both powers (2.1e-16 and 1.2e-11). Tier definitions in the paper and the forensic table now carry the beta column.

---

## Section 3.2 addition: Glyph Rotation (optional, high-dpi only, scoped tightly)

Add small sub-degree per-character rotation to the Carrier 1 perturbation vocabulary ONLY as an optional sub-carrier in the above-200-dpi rung of the dpi ladder (crops and zoomed captures; it is high spatial frequency and dies on full-page WhatsApp sends at ~137 dpi). It is not a new identification layer; it is added Carrier 1 capacity competing with kerning jitter and FontCode-style outline perturbation for the same psychovisual budget in the same dpi rung. The Section 3.2 capacity-measurement protocol decides empirically: measure all three (rotation, kerning, outline) under the leak corpus and keep whichever gives the best bits-per-detectability.

Caveat to implement, rectification aliasing. Per-glyph rotation aliases with camera-induced skew, because the blind rectifier recovers geometry from text baselines. The decoder must model camera skew as a smooth low-order field (global rotation plus a per-line linear trend fitted across many glyphs) and read intended rotation as the per-glyph high-frequency residual around that field. Any residual coupling directly injects symbol errors into this sub-carrier only. This coupling is the argument for keeping rotation strictly optional and out of the core. Do not over-invest.

---

## Section 5 flag: NEET Forensic Narrative Verification (action item)

The 2024 leak narrative as written in v0.2 Section 5 (8:02 am strong-room entry, seal removed and resealed with a lighter, photo relay by 9:23 am, solved by 10:15 to 10:40, 155 beneficiary students) is more specific than open secondary sources reliably confirm. ACTION ITEM, blocking for the citable paper: VERIFY AGAINST PRIMARY SOURCE, the CBI chargesheet or the CBI's written Supreme Court submission, before any of these specifics enter the paper. Until verified, the paper may state only the coarse facts (leak at a Jharkhand center on exam morning, complicit custodian, photographs of the paper, CBI investigation) with secondary-source citations marked as such. Do not build the deployment case study's forensic timeline on secondary reporting.

---

## Build Spec (the point of v0.3): Smoke Test First

Priority order is strict: A then B. A exists to fail cheaply.

### A. Smoke test (2 to 4 weeks solo): is the physical channel hopeless or not

Single carrier (Brassil word-shift and line-shift, the most downscale-robust), one page, no Tardos, no collusion. Pipeline: encode a fixed 64-bit PRN payload, print on a mono laser at 600 dpi, photograph with one phone flat in good light, one WhatsApp hop, blind decode, read one number.

Shipped and container-verified (smoke_test/):
- encode.py: 300 dpi A4 render, 45 lines. Line-shift in triplets (control, marked, control), marked baseline +/- 2 px, 15 bits/page. Word-shift on ALTERNATING interior words only, gap +/- 3 px, ~273 bits/page. The alternation matters: adjacent coded words share a gap and their shifts cancel (intersymbol interference); this bug was found and fixed during container verification, clean-image word accuracy went from 87.7 percent to 100 percent. Sidecar JSON carries ground truth for scoring only.
- channel.py: synthetic pre-print sanity channel (rotation, mild perspective, blur, WhatsApp/Telegram-grade downscale and JPEG). Sanity only, never for reported numbers.
- decode.py: blind. Deskew by profile-variance search, line segmentation from row profiles, per-line baseline as the robust median of connected-component bottoms with descender rejection, line bits from baseline-spacing differentials, subpixel gap widths by threshold-crossing interpolation, word bits from adjacent-gap differential signs. Sign decisions only, so the decoder is scale-free across capture resolutions. Meta JSON is used only to score.

Container-verified synthetic sanity results (real print-photo numbers WILL be worse, the synthetic channel has no paper texture, printer PWM, sensor noise, or page curl):
- Clean: line 15/15, word 273/273, payload 64/64.
- Synthetic WhatsApp (1600 px, q78, rot 0.4, blur 1.0): 100 percent both carriers.
- Double hop (harsh first hop then 1600 px q70): 100 percent both.
- Harsh 1200 px (rot 1.5, blur 1.8, q65): line 14/15, word 273/273.
- Unmarked control through the WhatsApp channel, scored against marked ground truth: line 0.47, word 0.54, chance level. The decoder reads embedded signal, not layout artifacts. Run this control in the real-world pass too; if it scores high, every other number is meaningless.

Go/no-go on REAL captures: GO if word-shift raw accuracy >= 0.85 or line-shift >= 0.90. NO-GO if the better carrier is under 0.60, meaning the physical channel eats the geometry and the design needs larger shifts or a different carrier before further investment.

### B. Corpus harness (6 to 10 weeks): the make-or-break gate and the benchmark artifact

As specified in harness/README.md, unchanged from the v0.3 instruction: 35 physical documents (3 printers x 2 stocks x 5 variants plus 5 unmarked controls), ~1,200 real captures over sampled (phone x angle x lighting x framing) cells, digital multipliers for messaging chains and AI cleanup applied to real captures only, frozen splits with no shared physical page, sidecar JSON per capture. Shipped: metrics.py (SER, k_eff as summed per-symbol implied-BSC capacities from LLRs, and the analytic tier lookup implementing the power-corrected master inequality, self-test reproduces every v0.2 worked cell), apply_channels.py (messaging chains implemented with mid-2026 app parameters, re-verify before each build, AI passes stubbed as explicit external commands for the GPU box), run_bakeoff.py (corpus walker enforcing the synthetic-exclusion and split rules, emits the per-cell CSV that pivots into the framing x messaging x cleanup heatmaps; decoder hooks are the TODOs, Carrier 2 training happens on the local GPU box).

Assumption stated inline: the smoke-test decoder handles full pages; fragment-capable decoding (line-count mismatch tolerance, partial-page alignment) is deliberately deferred to the harness phase, because the smoke test's only job is the physical-channel go/no-go.

---

## Honest downside, once

The synthetic 100-percent numbers are decoder-logic verification, not evidence the channel works. The real risks the smoke test exists to expose are exactly the ones the simulator cannot produce: printer geometric noise at the 1 to 3 px scale of the shifts (laser PWM jitter, paper feed wow), hand-held defocus and rolling-shutter skew that vary across the page, and page curl that bends baselines nonlinearly. If real word-shift accuracy lands under 0.60, the honest reading is that sub-pixel geometry does not survive consumer printing plus phone optics at these amplitudes, and the design must either raise amplitudes (visibility cost, measure it psychovisually) or shift weight to Carrier 2, which changes the capacity budget and weakens the fragment tiers. That is a real possible outcome and it is exactly what A is for. Separately, the Section 1 conjecture is now sharper but still a conjecture; if the phase-transition bound resists proof, the paper's flagship theory claim downgrades to the proven containment plus empirical Stage 0 results, which is still publishable but weaker.
