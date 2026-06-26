# Compiled AI Benchmark

*A reproducible benchmark for the claim that repeated AI workflows can be routed or
compiled into cheaper operational artifacts while preserving frontier-level quality
where the task allows it.*

Status: v2 evidence package · Last updated: 2026-06-26

---

## The Question

When a business workflow repeats, should every execution pay for a frontier agent to
reason from scratch?

This benchmark tests a narrower, falsifiable claim:

> On repeatable workflows, cheap/open models plus routing can match a frontier
> baseline at lower per-run cost, but the savings shrink as task difficulty rises
> and the right topology depends on latency requirements.

The important phrase is **match a frontier baseline**. Cheap outputs only count as
wins when they preserve task success.

See [`DESIGN.md`](DESIGN.md) for the full pre-registered design, hypotheses, cost
model, and kill conditions.

---

## What Is In This Package

| file | purpose |
|---|---|
| [`DESIGN.md`](DESIGN.md) | Pre-registered design: hypotheses, arms, cost model, kill conditions |
| [`RESULTS.md`](RESULTS.md) | Evidence log from v0 through v2, including caveats |
| [`WRITEUP.md`](WRITEUP.md) | Short public-facing results narrative |
| [`run.py`](run.py) | Arm runner for single-shot frontier, open model, and simple cascade |
| [`sweep.py`](sweep.py) | Two-cheap-model disagreement-gate Pareto sweep |
| [`harden.py`](harden.py) | v2 hard-invoice run: 3-model ensemble, continuous gate, latency, upfront router |
| [`data/pareto_invoices.csv`](data/pareto_invoices.csv) | Invoice cost/quality sweep |
| [`data/pareto_support_triage.csv`](data/pareto_support_triage.csv) | Support-triage cost/quality sweep |
| [`data/harden_invoices_frontier.csv`](data/harden_invoices_frontier.csv) | v2 cost/quality/latency sweep |

---

## What You Can Use It For

This repo is not only a fixed invoice/support benchmark. It is also a template for
testing whether *your* repeated workflow should run cheap-only, frontier-only,
cascaded, or upfront-routed under a cost, quality, and latency contract.

To adapt it to a new workflow:

1. Define the task shape in [`loaders.py`](loaders.py):
   - extraction: fields to extract and optional numeric fields
   - classification: one label field plus an allowed-label enum
2. Provide ground-truth examples:
   - each sample needs `text` and expected `fields`
   - examples can come from a JSONL file, CSV, public dataset, or internal eval set
3. Reuse the existing arms in [`arms.py`](arms.py):
   - frontier single-shot
   - cheap/open model
   - cheap-first cascade
4. Reuse or extend scoring in [`scoring.py`](scoring.py):
   - exact document success
   - per-field accuracy
   - label accuracy
   - custom domain tolerances
5. Run the benchmark:
   - [`run.py`](run.py) for cheap/open vs frontier vs simple cascade
   - [`sweep.py`](sweep.py) for a cost/quality Pareto curve
   - [`harden.py`](harden.py) when you need p50/p99 latency and upfront routing

Minimal sample shape:

```json
{"text": "Customer: I lost my debit card and need to block it.", "fields": {"intent": "cash_withdrawal_card"}}
```

Minimal extraction shape:

```json
{"text": "Invoice INV-100 total due $42.50", "fields": {"invoice_number": "INV-100", "total_amount": "42.50"}}
```

The practical question this repo helps answer:

> Given a quality bar and latency SLA, what is the cheapest runtime topology that
> still works for this workflow?

---

## Task Suite

The current package covers two workflow types:

1. **Invoice extraction**
   - Easy invoice fields: invoice number, date, total
   - Hard invoice fields: adds IBAN and seller tax ID
   - Dataset source: `mychen76/invoices-and-receipts_ocr_v1`

2. **Support-ticket triage**
   - 77-way banking intent classification
   - Dataset source: `mteb/banking77`

This is intentionally small. The goal is to establish the cost-vs-difficulty curve
before expanding into more archetypes.

---

## Arms And Routing Topologies

| arm/topology | description | what it tests |
|---|---|---|
| **Frontier only** | Claude Opus single-shot structured output | Quality and cost baseline |
| **Open only** | Cheap/open model single-shot structured output | Whether the task is easy enough to run cheap directly |
| **Disagreement cascade** | Two cheap models run first; escalate to frontier on disagreement | Batch/async routing where tail latency is less important |
| **3-model ensemble cascade** | Cheap ensemble majority vote; escalate below confidence threshold | Continuous confidence gate and smoother Pareto curve |
| **Upfront router** | Input-only logistic gate chooses cheap or frontier before any LLM call | Interactive routing where p99 latency matters |

The routing result is not a single magic multiplier. It is an operating curve:
quality, cost, frontier fraction, and latency move together.

---

## Headline Results

| task | best cost-saving operating point | quality | cost saving | frontier fraction |
|---|---:|---:|---:|---:|
| Easy invoices | Open only | matches frontier | ~215x | 0% |
| Support triage | Disagreement cascade | matches frontier | 3.1x | 32% |
| Hard invoices | Cascade, relaxed parity knee | 0.62 vs 0.66 frontier | ~2x | 50% |
| Hard invoices | Strict parity | 0.66 vs 0.66 frontier | ~1.1x | 92% |

The real finding:

> Routing savings shrink with task difficulty. Easy repeated work can leave the
> frontier path entirely; medium tasks benefit from selective escalation; hard tasks
> often need the frontier most of the time.

The latency finding:

> Cascades are good for batch workflows, but they worsen p99 latency because the cheap
> leg sits on the critical path and escalation stacks the frontier call. Interactive
> surfaces need an upfront router or a deterministic cheap path.

---

## Setup

```bash
git clone https://github.com/snehalnair/compiled-ai-benchmark.git
cd compiled-ai-benchmark
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI-compatible endpoint for open/cheap models:
export OPEN_API_KEY=...
export OPEN_BASE_URL=https://openrouter.ai/api/v1

# Pin exact model IDs and prices for every run.
export OPEN_MODEL='qwen/qwen-2.5-7b-instruct'
export OPEN_INPUT_PRICE_PER_M=0.04
export OPEN_OUTPUT_PRICE_PER_M=0.10

export OPEN_MODEL_2='meta-llama/llama-3.1-8b-instruct'
export OPEN2_INPUT_PRICE_PER_M=0.02
export OPEN2_OUTPUT_PRICE_PER_M=0.03

export OPEN_MODEL_3='mistralai/mistral-small-24b-instruct-2501'
export OPEN3_INPUT_PRICE_PER_M=0.05
export OPEN3_OUTPUT_PRICE_PER_M=0.08
```

Prices are pinned in [`config.py`](config.py) and should be treated as part of the
experiment. If model prices change, rerun and date the new snapshot.

---

## Reproduce The Runs

Smoke test:

```bash
python run.py --dataset synthetic --limit 6 --arms B_frontier_singleshot,D_compiled_open,R_routed_cascade
```

Easy invoice extraction:

```bash
python run.py --dataset invoices_ocr --limit 40 --arms B_frontier_singleshot,D_compiled_open,R_routed_cascade
```

Hard invoice Pareto sweep:

```bash
python sweep.py --dataset invoices_ocr --hard --limit 50 --workers 6
```

Support triage Pareto sweep:

```bash
python sweep.py --dataset support_triage --limit 50 --workers 6
```

v2 hard-invoice latency and upfront-router run:

```bash
python harden.py --limit 100 --workers 6
```

All scripts report mean cost per run, task success, bootstrap confidence intervals,
and frontier fraction where relevant. Sweep scripts also write CSVs under
[`data/`](data/).

---

## How To Read The Metrics

- **success**: strict task success. For extraction, all scored fields must be correct.
  For support triage, the intent label must match the ground truth.
- **field accuracy**: softer extraction metric, averaged over fields.
- **cost/run**: mean USD per document/message, using recorded token counts and pinned
  per-token prices.
- **xB**: times cheaper than the frontier single-shot baseline. Only meaningful at
  comparable quality.
- **frontier fraction**: percentage of cases routed to the frontier model.
- **p50/p99 latency**: modeled from measured component calls in `harden.py`; read the
  relative ordering, not the absolute milliseconds.

---

## Caveats

- Current invoice data is OCR text from a public dataset, not raw scanned images.
- Public datasets are cleaner than messy SME production workflows.
- Frontier baselines are zero/few-shot structured-output baselines, not heavily
  optimized task-specific systems.
- Self-hosted GPU total cost is not yet included.
- The upfront router in v2 is deliberately simple: six input features and a
  cross-fitted logistic model.
- Latency was measured under concurrent load with provider retries, so absolute p99
  numbers are noisy.

These caveats are part of the point: the benchmark is meant to make claims smaller,
clearer, and falsifiable.

---

## Next Work

1. Add a self-hosted GPU cost track.
2. Add raw scanned receipt/PDF extraction to separate OCR difficulty from reasoning.
3. Add one judgment-heavy workflow to locate where routing and compilation break.
4. Strengthen the upfront router with embedding/input features.
5. Define a workflow-card format: task spec, eval suite, route topology, cost profile,
   latency profile, and drift checks.
