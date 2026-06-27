# The Determinism Dividend — Benchmark & Proof Design

*Working title for the credibility anchor: a reproducible benchmark showing that compiling agentic workflows into deterministic pipelines on open-weight models cuts per-execution cost at equal task quality.*

Status: v0 design · Owner: Snehal Nair · Last updated: 2026-06-26

---

## 1. The claim we are testing (falsifiable)

> For **repeatable** enterprise workflows, compiling agentic reasoning into **deterministic** pipelines that run on **small / open-weight** models reduces per-execution cost by N× **at equal task-success rate**, after a one-time authoring cost that amortizes within a small number of runs.

The phrase **"at equal task-success rate"** is the entire scientific contribution. Cost-savings claims are cheap and ubiquitous; *proven cost savings at proven quality parity* are rare. If we cannot hold quality, we report that honestly — that is also a finding.

A second, underrated part of the claim worth measuring: deterministic pipelines are **reproducible and auditable** (near-zero run-to-run variance). For SMEs in finance, legal, health, and compliance, that is independently valuable — sometimes more than cost.

---

## 2. Pre-registered hypotheses

We commit to these *before* running, to avoid post-hoc storytelling.

- **H1 (Cost).** Compiled pipelines on open-weight models cost ≥5× less per run than a frontier agentic baseline at iso-quality.
- **H2 (Quality parity).** On structured/extraction-heavy archetypes, the compiled-open arm reaches within δ = 2 percentage points of the best frontier baseline's success rate.
- **H3 (Amortization).** One-time authoring/compile cost breaks even within N* ≤ 100 runs for the typical archetype.
- **H4 (Determinism).** Compiled pipelines show ≥10× lower run-to-run output variance than agentic baselines on identical inputs.
- **H5 (Where it breaks).** On judgment-heavy / open-ended archetypes, the compiled-open arm fails iso-quality without an LLM escape-hatch node — i.e. pure determinism has a ceiling. *(We expect to confirm this; naming the limit is credibility, not weakness.)*
- **H6 (Pareto routing).** A cheap difficulty-gate can route only a *minority* fraction `f` of inputs to the frontier model and the rest to open-weights while holding iso-quality — testing the assumption that ~20% of cases drive the need for frontier capability. We **measure `f`**, not assume it; the realized split per archetype is itself a headline result.

---

## 3. Experimental arms

The point is not "agentic vs deterministic" — it is to **decompose** the savings so we can attribute them. Each arm changes one variable.

| Arm | Description | Isolates |
|-----|-------------|----------|
| **A — Frontier agentic** | ReAct/tool-loop agent on a frontier model, re-plans each run. The "naive expensive" baseline most SMEs would build. | Upper-bound cost & quality |
| **B — Frontier single-shot** | Same frontier model, well-prompted, no agent loop. | Cost of the agent loop itself |
| **C — Compiled / frontier-small** | Workflow compiled to a deterministic DAG; nodes run on a *small frontier* model. | Gain from compilation (structure) |
| **D — Compiled / open-weight** ⭐ | Same DAG, nodes routed to open-weight models. **The hero arm.** | Gain from open-model swap |
| **E — Compiled / open + optimized** | D plus prompt-caching, context pruning, per-node right-sizing. | Gain from the full stack |
| **R — Routed (frontier↔open)** ⭐ | A cheap gate scores each input by difficulty; hard cases → frontier, the rest → open-weight, via a **cascade** (run open first, escalate on low confidence / failed validation). Composable with C–E. | Gain from complexity-routing; **empirically tests the 80/20 Pareto assumption** |

Reading A→E left-to-right tells the decomposition story: *how much saving comes from removing the loop (A→B), from compiling (B→C), from going open (C→D), from optimization (D→E)* — at each step we also report the quality delta. **Arm R is orthogonal**: rather than committing every input to open-weights, it sends only the hard minority to the frontier. Sweeping its escalation threshold traces the full **cost–quality Pareto frontier**, and the realized frontier fraction `f` is a headline result in its own right (H6).

---

## 4. The task suite (workflow archetypes)

Chosen to (a) be genuinely common across SMEs, (b) have **objective ground truth** so success rate is not a matter of opinion, and (c) span a **difficulty gradient** from deterministic to judgment-heavy — so we can locate the boundary in H5.

| # | Archetype | SME relevance | Candidate public dataset (verify license) | Expected difficulty |
|---|-----------|---------------|---------------------------------------------|---------------------|
| 1 | Invoice / receipt → structured fields | Accounting, AP automation | CORD, SROIE | Low (extraction) |
| 2 | Form / document field extraction | Ops, onboarding | FUNSD, DocVQA | Low–Med |
| 3 | Support email → intent + routing | Customer service | Banking77, public ticket sets | Low–Med |
| 4 | Contract clause extraction / flagging | Legal, procurement | CUAD | Medium |
| 5 | Compliance check (doc vs policy) | RegTech, finance | Synthetic policy+doc pairs | Med–High |
| 6 | Meeting notes → action items / CRM rows | Sales ops | Synthetic / public transcripts | Medium |
| 7 | Multi-step report generation from tables | Finance, management | Synthetic structured inputs | High (open-ended) |
| 8 | Lead enrichment + qualification | Sales | Synthetic + public firmographics | High (judgment) |

Use public datasets for reproducibility; supplement with **synthetic** data (LLM-generated, human-spot-checked) where private SME data would otherwise be needed. Pin dataset versions and licenses in the repo. Start with 1, 3, and 4 — one easy extraction, one classification, one mid-difficulty — to get signal fast.

**Open-weight model pool to evaluate** (pin exact versions + prices on the run date — prices move): Qwen, Llama, Mistral, DeepSeek, Gemma, Phi families. The measured benchmark uses cheap hosted inference providers as the open-model baseline. Self-hosted deployment is handled separately as sensitivity analysis because its cost depends on serving stack, quantization, utilization, warm/cold-start policy, and SLA (see §6).

---

## 5. Metrics

**Primary**
- **Task success rate** per archetype, against ground truth (exact-match / F1 for extraction; accuracy for classification; rubric-scored for generation).
- **Cost per execution** (see cost model §6), split into **one-time authoring/compile** vs **per-run**.
- **Headline figure:** cost-reduction factor at iso-quality = `C_run(baseline) / C_run(arm)`, reported **only** for arms that pass the quality bar.

**Secondary**
- **Amortization / break-even** N* (§6).
- **Run-to-run variance** (determinism): run each arm K=10× on identical inputs; report output disagreement rate. (H4)
- **Latency** per run.
- **Maintenance/drift proxy:** re-run on a perturbed input distribution; measure success-rate decay. (This is the cost the *platform* later sells against.)

**Quality bar (iso-quality), pre-registered:** an arm "qualifies" if `success_rate(arm) ≥ best_baseline_success_rate − δ`, with non-inferiority margin **δ = 2 pp**. Cost savings are reported only for qualifying arms; for non-qualifying arms we report the quality gap plainly.

---

## 6. Cost model (be explicit and honest)

Per-run cost for an arm, summed over pipeline nodes:

```
C_run = Σ_nodes ( tokens_in · price_in  +  tokens_out · price_out )      # API-priced
C_run = (GPU_$per_hr · runtime_hr) + amortized_idle + ops_overhead       # self-hosted sensitivity only
```

**Router arm (R) blended cost.** With a cheap gate routing a fraction `f` of inputs to frontier and `1 − f` to open-weight:

```
C_run(R) = price_gate + f · C_run(frontier) + (1 − f) · C_run(open)
```

Let `r = price_open / price_frontier` and `g = price_gate / C_run(frontier)`. Savings vs frontier-only ≈ `1 / ( f + (1−f)·r + g )`. **`f` is measured, not assumed** — the 80/20 Pareto claim is a hypothesis the benchmark tests per archetype. Sweep the router's escalation threshold to trace the **cost–quality Pareto frontier** and report the *knee*: the cheapest operating point that still clears the quality bar.

One-time authoring/compile cost (frontier reasoning to author + validate the pipeline):

```
C_compile = C_author + C_eval_to_validate
```

Total over N runs and break-even vs baseline B:

```
C_total(N) = C_compile + N · C_run
N*  =  C_compile / ( C_run(baseline) − C_run(arm) )      # break-even run count
```

**Honesty rules** that make this credible rather than marketing:
1. Do not present self-hosted GPU cost as a headline benchmark number. Treat it as a **deployment sensitivity card**: model revision, serving stack, quantization, hardware price, workload shape, utilization, warm/cold-start policy, p50/p95/p99, quality delta, and ops overhead. Compare only at iso-quality and stated SLA.
2. **Pin model versions and per-token prices to a dated snapshot.** Prices fall fast; a benchmark with undated prices is worthless in 6 months.
3. Report the **frontier-price-decline sensitivity**: re-run the headline with frontier prices cut 50%/75% to show the conclusion is robust (compilation + amortization compound *with* falling prices, not against them).

---

## 7. Methodology & controls

- **Held-out test sets.** Author/compile pipelines on a dev split; evaluate on an untouched test split. No peeking.
- **Variance.** K=10 runs per (arm × archetype). Report mean ± 95% CI; use a non-inferiority test against the δ margin, not a naive t-test.
- **Judging.** Objective ground truth where it exists (1–4). For generative archetypes (5–8), use an LLM-judge **plus** human spot-check on a 10–20% sample, and **report judge–human agreement** so the judge itself is validated.
- **Fairness.** Same input data, same retries policy, same max-token budgets across arms. Document every prompt; check the frontier baselines are *strong* (a weak baseline inflates your win and destroys credibility).
- **Full reproducibility.** Open harness, pinned datasets/models/prices, seeds where applicable, one-command rerun. This is the artifact that makes skeptics replicate instead of dismiss.

---

## 8. What would falsify the thesis (pre-registered)

State these up front — pre-registering your own kill-conditions is the strongest credibility signal you can send:

- Compiled-open arm **cannot** reach iso-quality on the *extraction* archetypes (1–2) → core thesis fails.
- Cost savings **vanish** once self-hosting overhead and authoring cost are honestly included → thesis is a pricing artifact, not architecture.
- Break-even N* is so high (e.g. >10k runs) that few SMEs reach it → economically irrelevant.
- Savings **disappear** under the 75%-frontier-price-cut sensitivity → "models get cheaper" beats you.

If any fires, that is a publishable negative result and saves you from building the wrong company.

---

## 9. Deliverables (the credibility outputs)

1. **Public repo** — reproducible harness + datasets/configs + leaderboard table.
2. **Technical report** (arXiv-style) — the rigor artifact; doubles as the seed of an academic paper.
3. **One-page result card** — the headline N× number, with the honesty caveats, for blog/Show HN/pitch.
4. **A reusable "workflow card" format** — how each archetype's compiled pipeline is specified. *This format is a quiet land-grab: define it well and it becomes the interchange standard your eventual marketplace lists.*

---

## 10. Phasing

- **v0 (≈2–3 weeks):** archetypes 1, 3, 4 · arms A, B, D · cost + success-rate only · pipelines compiled **by hand**. Goal: a directional signal — is there a there there?
- **v1 (≈4–6 weeks):** all arms A–E · add variance, amortization, price-sensitivity · LLM-judge validated against humans · publish repo + report.
- **v2:** full 8 archetypes · one reference self-hosted deployment card as sensitivity analysis · drift/maintenance experiment · invite external replication.

Manual compilation in v0 is deliberate: prove the *economics* before investing in the auto-compiler (your eventual OSS Phase 1). Don't build the tool until the benchmark says the tool is worth building.

---

## 11. Threats to validity (keep visible)

- **Cherry-picked archetypes.** Mitigate with the difficulty gradient + publishing the losers (H5).
- **Weak baseline inflation.** Mitigate by having a frontier-savvy reviewer try to *beat* arms A/B.
- **Determinism ≠ correctness.** A deterministic pipeline can be reproducibly wrong; that's why variance and success-rate are separate axes.
- **Generalization.** SME workflows are messier than public datasets. Flag this; it's the bridge to Phase-2 design-partner case studies on real data.
```
