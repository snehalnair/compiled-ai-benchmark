# The Cost-Vs-Difficulty Curve For Compiled AI Workflows

*Early benchmark result, 2026-06-26.*

Agents are good at figuring out work. Repeated business workflows need something
cheaper and more predictable than paying an agent to rediscover the same structure
on every run.

This benchmark asks a narrow question:

> Can cheap/open models plus routing match a frontier model at lower per-run cost?

The answer is not a single multiplier. It is a curve.

---

## Result In One Sentence

On easy repeated work, cheap models can replace the frontier path entirely; on medium
work, routing can preserve frontier quality at materially lower cost; on hard work,
the savings shrink and latency topology starts to matter more than raw cost.

---

## What We Tested

Two workflow types:

- **Invoice extraction**: structured fields from OCR text.
- **Support-ticket triage**: 77-way banking intent classification.

Three routing styles:

- **Open only**: run a cheap/open model directly.
- **Cascade**: run cheap models first, escalate uncertain cases to the frontier.
- **Upfront router**: choose cheap or frontier before the LLM call to preserve tail latency.

All results use pinned model prices and recorded token usage. Cost savings are only
interpreted as wins when task quality is comparable to the frontier baseline.

---

## The Curve

| task | operating point | quality | saving vs frontier | frontier fraction |
|---|---|---:|---:|---:|
| Easy invoices | Open only | matches frontier | ~215x | 0% |
| Support triage | Disagreement cascade | matches frontier | 3.1x | 32% |
| Hard invoices | Cascade knee | 0.62 vs 0.66 frontier | ~2x | 50% |
| Hard invoices | Strict parity | 0.66 vs 0.66 frontier | ~1.1x | 92% |

The important pattern:

> The harder the task is for small models, the more work has to stay on the frontier
> path, and the smaller the routing win becomes.

That is the result a credible benchmark should produce. If every task showed the same
10x or 100x saving, the benchmark would probably be measuring a weak baseline or a
cherry-picked task.

---

## Why The Easy Task Matters

On clean invoice fields, the cheap/open model matched the frontier baseline at roughly
215x lower cost. The router did not help because there was almost nothing to route:
the small model could already do the work.

This is the purest form of the compiled-workflow claim. Once a task is structured,
repeated, and easy enough, the frontier model can leave the runtime entirely.

---

## Why The Support-Triage Task Matters

Invoice extraction alone could be dismissed as an extraction trick.

Support triage is different: a 77-way classification/routing problem. Here, open-only
lagged the frontier, but a simple disagreement cascade matched frontier accuracy while
routing only 32% of cases to the frontier, giving a 3.1x cost reduction.

This matters because it shows the same pattern outside field extraction:

> cheap models handle the easy majority; the frontier is reserved for the ambiguous
> minority.

---

## Why The Hard Invoice Task Matters

The hard invoice setting added long alphanumeric fields like IBAN and seller tax ID.
The cheap ensemble reached only 43% strict success, while the frontier reached 66%.

At strict parity, the cascade had to escalate about 92% of cases, leaving only a 1.1x
cost saving. The better operating point was the knee: escalate about 50% of cases,
reach 0.62 success versus 0.66 for the frontier, and cut cost by roughly 2x.

This is the honest boundary:

> routing still helps in the messy middle, but it does not magically make hard tasks
> cheap.

Sometimes the frontier is the right runtime.

---

## The Latency Finding

The v2 run measured component latencies and modeled two topologies.

Cascade routing worsens p99 latency because the cheap leg sits on the critical path.
If a case escalates, the frontier call is stacked after the cheap calls. On hard invoices,
cascade p99 was roughly 13-15 seconds versus roughly 11 seconds for frontier-only.

The upfront router preserved frontier-like p99 by committing to one path before any
LLM call.

The mature way to state this:

> Cascades are a cost topology, not an interactive latency topology. In interactive
> settings, routing must happen *before* generation, or be avoided entirely through
> compilation and caching.

So latency-sensitive workflows need a routing *policy* — `route(request, sla_tier) →
topology` over a ladder of pre-execution signals, not a single router:

1. **Cache hit** — return immediately.
2. **Compiled deterministic path** — template parser, rules, lookup, schema validation (µs–ms).
3. **Upfront cheap path** — known-safe, low-risk inputs go to a small/open model.
4. **Upfront frontier path** — novel, high-risk, complex, or uncertain inputs go straight to the frontier.
5. **Cascade** — batch/async only, where tail latency does not matter.
6. **Hedged parallel, with a delay τ** — premium/high-stakes interactive: fire cheap, and if no
   confident answer arrives by τ, fire the frontier. Caps the tail while paying for the frontier
   only on the slow tail. A dial, not a mode.

The upfront logistic router we benchmarked is only the simplest proof that *some*
pre-generation signal exists; a production gate uses template identity, embedding
distance to known-good clusters, OCR quality, schema complexity, customer history,
and risk/SLA policy.

---

## What This Says About Agents

This is not an anti-agent result.

The claim is that agents should not sit in the hot path for repeated work when their
output can be compiled, tested, routed, and monitored.

The better architecture is:

1. Use an agent to discover or author the workflow.
2. Compile the repeated parts into a cheaper operational artifact.
3. Attach evals, traces, thresholds, and escalation rules.
4. Run the artifact cheaply.
5. Use an agent again when drift is detected and the artifact needs retooling.

Agents are for figuring out the work. Compiled workflows are for running it.

---

## What This Does Not Prove Yet

This benchmark does not yet prove:

- production robustness on messy SME data
- self-hosted GPU total cost
- raw image/PDF extraction quality
- autonomous workflow compilation
- long-term drift maintenance
- performance on open-ended judgment-heavy work

Those are the next tests. The point of this package is smaller: establish a measured,
reproducible cost-vs-difficulty curve and avoid claiming a universal multiplier.

---

## Why This Is Useful

Most AI workflow discussions collapse into one of two claims:

- "Use agents for everything."
- "Use small models because they are cheaper."

The benchmark points to a more operational answer:

> choose the cheapest runtime topology that meets the quality, latency, and
> auditability contract for that workflow.

That contract is the real artifact, and it is **four-way**, not a savings number:

- **quality** — held-out eval bar,
- **cost** — per run,
- **latency** — p95/p99 target and allowed topology,
- **determinism / auditability** — output variance, and the fraction of traffic served by
  the deterministic path (rung occupancy — which is itself the cost-vs-difficulty curve).

The deterministic path is the strongest rung: simultaneously the cheapest, the
lowest-latency, and the most auditable. So the real artifact is not a router but a
**compiler that maximizes the fraction of traffic that never touches a model** — the
router is only the fallback for what won't compile. The same compiler ships three SLA
profiles: **batch** optimizes cost, **interactive** optimizes p99, **regulated**
optimizes auditability and governed promotion.

The work ahead is to turn that contract into a standard workflow card.
