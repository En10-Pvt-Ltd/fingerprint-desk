# Forensic Tier Table (Tardos-fallback cells)

Largest tolerable symbol-error rate `pmax` that still clears the courtroom tier, by region scale, under each p-semantics and detection power. These are the **Tardos-fallback** cells (coalition drift `(2/pi)*f(p)*sqrt(k)/c`), distinct from the Stage 0 c-independent single-source table in `stage0-soundness.md` (drift `d_tau=0.8627`).

Parameters: `n = 5000`, courtroom `budget = 5e-07` (Stage 0 ledger split of the 1e-6 courtroom allocation), `Qinv(budget/n)` in the inequality.

`flip` factor `(1-2p)` is the hard-decision floor; `erasure` factor `(1-p)` applies only if unreadable symbols are truly dropped. `soft` (the production mode) has no scalar p-factor and is not tabulated here because pmax is p-independent by construction. `infeasible` = budget unreachable even at zero error.

| Region scale | c | k | flip β=0.5 | flip β=0.9 | erasure β=0.5 | erasure β=0.9 |
|---|---|---|---|---|---|---|
| full paper | 5 | 8000 | 0.221 | 0.164 | 0.441 | 0.329 |
| single page | 2 | 1000 | 0.184 | 0.120 | 0.368 | 0.241 |
| single question (c=1) | 1 | 200 | 0.147 | 0.076 | 0.293 | 0.151 |
| single question (c=2) | 2 | 200 | infeasible | infeasible | infeasible | infeasible |

