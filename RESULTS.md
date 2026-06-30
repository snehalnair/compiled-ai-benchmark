# v0 results — invoice extraction (archetype #1)

Run: **2026-06-26** · 6 synthetic plain-text invoices · prices as of 2026-06-26
Frontier: `claude-opus-4-8` ($5 / $25 per 1M) · Open: `qwen/qwen-2.5-7b-instruct` via OpenRouter ($0.04 / $0.10 per 1M)

| arm | success (strict) | field acc | cost/run | ×B | frontier fraction f |
|-----|:---:|:---:|---:|---:|:---:|
| A — frontier naive (opus, adaptive thinking) | 1.00 | 1.00 | $0.00291 | 1.6× | 100% |
| B — frontier single-shot (opus, structured) | 1.00 | 1.00 | $0.00475 | 1.0× | 100% |
| D — compiled / open (Qwen-2.5-7B) | 0.83 | 0.97 | $0.00001 | **367×** | 0% |
| R — routed cascade (open→escalate) | **1.00** | 1.00 | $0.00077 | **6.2×** | **17%** |

## Reading

- **Naive substitution fails the bar.** The open model alone is 367× cheaper but misses strict parity (83% vs 100%; 97% field-level). "Just use the cheap model" is *not* the architecture.
- **The router IS the architecture.** Running open-first and escalating only the failures matched frontier quality exactly (100%) at **6.2× lower cost**, sending only **17%** of documents to the frontier.
- **H6 (Pareto routing) — measured, not assumed:** the realized frontier fraction f ≈ 17%, close to the 20% assumption but derived from the data. The cheap open model genuinely handled the easy majority.

## Caveats (this is a smoke test, not a result)

- **n = 6.** "17%" is literally one escalated document; the "6.2×" rides on that single escalation. Directional only — v1 scales to ~50–100 docs with confidence intervals.
- Invoices are **plain text**, not scanned images/PDFs — isolates extraction reasoning from OCR/vision (a separate archetype).
- Open cost is the **OpenRouter API price**; self-hosted GPU deployment is not part of this measured result. It belongs in a separate sensitivity card that pins serving stack, quantization, utilization, warm/cold-start policy, quality delta, and SLA.
- The router gate is **validation-based** (escalate on a missing required field). v1 sweeps a confidence threshold to trace the full cost–quality Pareto curve and report the knee.
- The A < B cost inversion ($0.00291 < $0.00475) is within n=6 noise (adaptive thinking stays minimal on trivial docs); not a finding.

## What this earns

A directional green light: on a repeatable extraction workflow, **open-weight + frontier-routing reproduced frontier quality at ~6× lower cost**, with the open model carrying ~83% of the load. The manifesto's cost-at-parity claim now has a (small, honest) number behind it. Next: scale the set, sweep the router threshold for the Pareto curve, and add a second archetype. Self-hosted deployment should remain sensitivity analysis, not a headline result.

---

# v1.1 — public dataset, n=40, with confidence intervals

Run: **2026-06-26** · 40 invoices from `mychen76/invoices-and-receipts_ocr_v1` (HuggingFace; OCR text + structured ground truth; rendered/synthetic invoices, near-perfect OCR) · fields: invoice_number, invoice_date, total_amount (EU/US money-aware scorer) · frontier `claude-opus-4-8`, open `qwen/qwen-2.5-7b-instruct`.

| arm | success [95% CI] | field acc | cost/run | ×B | frontier fraction f |
|-----|:---:|:---:|---:|---:|:---:|
| B — frontier single-shot | 0.95 [0.88–1.00] | 0.98 | $0.00568 | 1.0× | 100% |
| D — compiled / open | 0.95 [0.88–1.00] | 0.98 | $0.00003 | **214.9×** | 0% |
| R — routed cascade | 0.95 [0.88–1.00] | 0.98 | $0.00003 | 214.9× | **0%** |

## Reading — and an honest complication

- **Cost-at-parity win is large, now with CIs.** The open 7B model **matches** the frontier (both 95%, field-acc 0.98) at **~215× lower cost**. Core thesis strongly supported on this task.
- **The router added nothing (f = 0%) — the key finding.** The open model never tripped the validation gate, *including on the ~5% it got wrong*: it returns plausible-but-wrong values (right shape, wrong number), which a presence/validation gate cannot catch. Lessons: (1) routing only pays with a real quality gap **and** a failure-detecting gate — this easy task has neither; (2) a presence-based gate is blind to confident errors → a real router needs a **correctness-correlated** signal (arithmetic consistency, self-consistency, or a cheap verifier), then a swept threshold.
- **"Measure f, don't assume it" vindicated:** f = 0% here vs 17% on harder v0 vs the 20% assumption. Frontier fraction = f(task difficulty × gate quality), not a constant.

## What it changes — the two runs bracket the thesis

- **Easy/clean task →** open-weight alone wins on cost at parity (215×); router redundant.
- **Harder task (v0) →** open-weight alone falls short; router recovers parity at a smaller-but-real saving (6.2×, f=17%).
The question that matters is therefore **gate design + where the difficulty boundary sits** (H5/H6).

## Caveats
- Invoices are **rendered/synthetic** (near-perfect OCR) → easy; real *photographed* receipts (CORD via OCR/vision) will be harder and are where routing should earn its keep.
- 3 clean fields; the brittle `seller`/address field was excluded.
- Gate is **presence-based** (this run's central finding); v1.2 replaces it with a correctness-correlated, swept gate.
- n=40 → CIs wide ([0.88–1.00]); n≥100 tightens them.

---

# v1.2 — disagreement-gate router, Pareto sweep (hard task, n=50)

Run: **2026-06-26** · 50 invoices, `invoices_ocr_hard` (5 fields incl. 22-char IBAN + seller tax-id — long alphanumerics where small models slip) · open1 `qwen/qwen-2.5-7b-instruct`, open2 `meta-llama/llama-3.1-8b-instruct`, frontier `claude-opus-4-8`. Gate: escalate when the two cheap models disagree on ≥ T fields; sweep T. Points → `data/pareto_invoices.csv`.

| operating point | success [95% CI] | cost/run | ×B | frontier fraction |
|-----------------|:---:|---:|---:|:---:|
| D open1-only | 0.26 [0.16-0.38] | $0.00003 | 228× | 0% |
| R disagree≥3 | 0.26 [0.16-0.38] | $0.00004 | 168× | 0% |
| R disagree≥2 | 0.30 [0.18-0.44] | $0.00045 | 15.4× | 6% |
| R disagree≥1 | **0.64 [0.50-0.76]** | $0.00470 | **1.5×** | 66% |
| B frontier-only | 0.66 [0.54-0.78] | $0.00700 | 1.0× | 100% |

## Reading

- **The hard task created the gap we needed:** open-alone 26% vs frontier 66%.
- **The disagreement gate is correctness-correlated** (unlike v1.1's presence gate). At its sensitive setting (escalate on ANY disagreement) the router hits **64% — statistically tied with frontier's 66%** (CIs overlap) — at **1.5× lower cost**, keeping 34% of docs on cheap models only. The kept-cheap docs are the ones the two models *agree* on — and those are mostly the correct ones, so agreement tracks correctness.
- **Knee = disagree≥1**; middle thresholds escalate too little to help on this hard task.

## The three runs together — the real shape of the thesis

| task difficulty | best open+routing result | saving at parity | frontier fraction f |
|---|---|---|---|
| easy (v1.1, clean) | open-weight ALONE | ~215× | 0% |
| medium (v0, messy) | router | ~6.2× | 17% |
| hard (v1.2, IBAN/tax-id) | disagreement router | ~1.5× | 66% |

**The cost advantage of open + routing is a function of task difficulty (~215× → ~1.5×), and the optimal frontier fraction rises with difficulty (0% → 17% → 66%). Measured, not assumed.** Open wins outright on easy tasks; the router earns its keep in the messy middle; very hard tasks send most docs to the frontier.

## Caveats
- Frontier itself caps at 66% strict here — exact-match on OCR'd long alphanumerics partly measures OCR fidelity, not extraction. The *relative* story (open 26 → router 64 ≈ frontier 66 at 1.5×) is the signal.
- Gate resolution is coarse with 5 fields; a continuous per-field confidence (or 3+ model votes) would smooth the curve.
- n=50; CIs still ≈ ±0.12.

---

# v1.3 — generality: support-ticket triage (classification, not extraction)

Run: **2026-06-26** · 50 customer messages from `mteb/banking77` (HF; 77-way intent classification = ticket routing) · same disagreement gate as v1.2 (Qwen-7B + Llama-8B → escalate to Opus on disagreement). Points → `data/pareto_support_triage.csv`.

| operating point | accuracy [95% CI] | cost/run | ×B | frontier fraction |
|-----------------|:---:|---:|---:|:---:|
| D open1-only | 0.70 [0.56-0.82] | $0.00002 | 544× | 0% |
| R disagree≥1 | **0.82 [0.70-0.92]** | $0.00338 | **3.1×** | 32% |
| B frontier-only | 0.82 [0.70-0.92] | $0.01045 | 1.0× | 100% |

## Reading

- **Generality confirmed — the thesis is not an extraction trick.** On a 77-way classification/routing task the disagreement router **matches the frontier exactly** (82% = 82%, identical CIs) at **3.1× lower cost**, routing only **32%** of tickets to the frontier. Open-alone has a real gap (70% vs 82%); the router closes it.
- **"Small models viable, agent not needed at runtime":** a 7B open model resolves 68% of tickets correctly on its own; the frontier is reserved for the ambiguous third.
- **Pattern holds across task TYPES:** f = 32% sits between the medium (17%) and hard (66%) invoice points — frontier fraction scales with task difficulty regardless of task shape.

## Caveat
- Frontier itself is 82% on 77-way Banking77 (fine-grained intents, zero-shot LLM; fine-tuned SOTA is higher). The relative story (open 70 → router 82 = frontier 82 at 3.1×) is the signal. n=50.

---

## Where the harness stands after v1.3

Two task types (extraction + classification), four public/synthetic datasets, real token+cost accounting, bootstrap CIs, a pluggable task interface (instruction + fields + optional label-enum), a two-model disagreement router, and a Pareto sweep. Genuinely the seed of the open-source benchmark (Phase 1).

---

# v2 — harden invoices: n=100, continuous gate, latency (p50/p99), upfront router

Run: **2026-06-26** · n=98 hard invoices (5 fields incl. IBAN/tax-id) · cheap ensemble = Qwen-7B + Llama-8B + Mistral-small-24B (all ≤$0.10/1M) majority vote · frontier Opus 4.8. Latency **modeled** from measured component calls (cheap leg = parallel max; cascade escalation adds frontier leg sequentially; upfront gate ~1 ms). Sweeps → `data/harden_invoices_frontier.csv`.

## At frontier parity

| operating point | success [95% CI] | cost/run | ×B | →frontier | p50 ms | p99 ms |
|---|:---:|---:|---:|:---:|---:|---:|
| Ensemble (3 cheap, vote) | 0.43 [0.33-0.53] | $0.00008 | 93× | 0% | 2148 | 6493 |
| Cascade @ parity | 0.66 [0.57-0.76] | $0.00650 | 1.1× | 92% | 4931 | **15149** |
| Upfront @ parity | 0.66 [0.57-0.76] | $0.00688 | 1.0× | 99% | 2581 | **11092** |
| Frontier only | 0.66 [0.57-0.76] | $0.00696 | 1.0× | 100% | 2580 | 11091 |

## Cascade cost × quality × latency curve (the real tradeoff)

| f→frontier | success | cost/run | p50 ms | p99 ms |
|---:|:---:|---:|---:|---:|
| 0% | 0.43 | $0.00007 | 2148 | 6493 |
| 13% | 0.47 | $0.00100 | 2249 | 12974 |
| 50% | 0.62 | $0.00356 | 3636 | 12974 |
| 81% | 0.63 | $0.00575 | 4567 | 14565 |
| 100% | 0.66 | $0.00703 | 5031 | 15149 |

## Reading — the latency answer, with data

- **Cascade routing always worsens the tail.** The cheap leg sits on the critical path and escalation stacks the frontier leg on top: cascade p99 is ~13–15 s at *every* operating point vs ~11 s frontier-only — strictly worse. Even at 100% escalation it pays the cheap leg first (15.1 s vs 11.1 s).
- **The upfront router preserves frontier-level tail** (p99 11.1 s ≈ frontier) by committing to ONE model — no stacking. This is the latency-safe topology for interactive SLAs.
- **Cost tradeoff:** the cheap ensemble is only 43% here (vs frontier 66%), so strict parity forces ~92–99% escalation → ~1.1× saving. The knee is ~f=50%: accept 0.62 (within CI of 0.66) for **~2× cheaper**. Past 50%, diminishing returns (the last 4 quality points cost 2× and add tail latency).
- **Difficulty, once more:** routing's cost win shrinks with task difficulty — 215× (easy) → 3.1× (triage) → ~2× (hard invoices, relaxed quality). The value is choosing the operating point per SLA, not a fixed multiplier.

## Caveats
- Latencies measured under concurrent load + retries (Mistral was upstream-rate-limited) → absolute ms inflated/noisy; the RELATIVE ordering (cascade tail > frontier ≈ upfront) is the signal.
- Upfront gate is a 6-feature cross-fitted logistic; a richer gate (embeddings, more features) could keep more docs cheap.
- 2 of 100 docs dropped after retries.

---

**Next (step 3 of the sequence): package + write up.** We now have extraction + classification generality, a cost-vs-difficulty curve, and a cost × quality × latency characterization with a clear interactive-vs-batch routing recommendation — enough for a credible public benchmark + results write-up. Self-hosted GPU deployment can be added later as a sensitivity card, not as another core benchmark axis.

---

# v3 — judgment tasks: "needs a frontier" is not predictable from difficulty (LegalBench)

Run: **2026-06-26** · LegalBench (Guha et al.) judgment-classification tasks, n=50–60 · frontier Opus 4.8; cheap Qwen-2.5-7B / Llama-3.1-8B via OpenRouter · A(thinking-on)/B(thinking-off)/D(open) + disagreement-router sweep. Points → `data/pareto_legalbench_*.csv`.

| task | frontier B [CI] | open D [CI] | disagreement router | escalated | verdict |
|---|---|---|---|---|---|
| `hearsay` (legal-evidence judgment) | 0.83–0.87 | **0.92 [0.85-0.98]** | 0.95 | 12% | open ≥ frontier |
| `personal_jurisdiction` (multi-step doctrine) | **0.94–0.96** | 0.62 [0.48-0.76] | 0.66 | 12% | frontier ≫ open; router fails |

(Frontier *with* thinking (arm A) ≈ thinking off — hearsay A=0.85/B=0.83; PJ A=0.90/B=0.96 — so the gap is not a thinking-off artifact.)

## Findings

- **"Judgment-heavy" ≠ "needs a frontier."** On `hearsay` the open 7B matches or beats Opus (0.92 vs 0.83–0.87) at ~357× lower cost; letting Opus *think* doesn't change it (a strong model can overthink a fixed rubric).
- **The real break-point is multi-step reasoning.** On `personal_jurisdiction` (apply the minimum-contacts doctrine to facts) the open 7B collapses to 0.62 vs the frontier's 0.94–0.96 — non-overlapping CIs, a genuine capability cliff.
- **Two superficially-identical tasks, opposite outcomes.** Both are "hard binary legal classification"; one needs no frontier, the other needs it outright. **You cannot predict the frontier fraction from intuitive difficulty — you must measure it.** This is the headline.
- **On the genuine break-point, the disagreement router FAILS** (escalates 12%, reaches 0.66 vs frontier 0.94): the two cheap models are *jointly* wrong and *agree*, so the gate never fires. Reasoning break-points produce **shared blindspots that inter-model agreement cannot detect** — a stronger form of the confident-error blindness from v1.1. Recovering frontier quality requires escalating ~everything (cost advantage → ~1×).

## What it changes
The gradient is now complete and richer than "savings shrink with difficulty": open wins outright (clean extraction; hearsay); router recovers parity (triage; hard-invoice); **frontier necessary *and routing fails*** (personal_jurisdiction — cheap path jointly and undetectably wrong). The frontier fraction *and whether routing even works* are per-task properties to MEASURE, not assume.

## Caveats
- n=50–60, single seed, CIs ±0.12. `diversity_1` excluded from the headline (80% "No" base rate; needs balanced accuracy).
- hearsay's open≥frontier is "matches" (overlapping CIs), not provably "beats"; per-example error analysis (do frontier errors cluster on hearsay exceptions?) is future work.
- LegalBench has per-task licenses; data is loaded at runtime, not redistributed; cite Guha et al.
