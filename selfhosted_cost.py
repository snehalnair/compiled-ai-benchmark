"""Self-hosted GPU deployment sensitivity analysis.

Turns the benchmark's "open-model cost = API sticker price" into the honest question
your reviewers will ask: at what sustained utilization does running the open model on
your OWN GPU beat paying per-token API pricing?

This is a parametric REGIME MAP, not a benchmark and not a measured point estimate
(we can't spin a GPU here). The throughput numbers are ILLUSTRATIVE defaults for a
~7B model under batched serving (vLLM / TGI) — replace them with YOUR measured
aggregate tokens/sec.

The contribution is the decision frontier: which deployment assumptions make self-hosting beat
per-token APIs, and which assumptions make APIs win. A single self-hosted number would
be misleading because throughput is an optimization frontier, not a constant:
quantization, vLLM/TGI continuous batching, speculative decoding, tensor parallelism,
batch shape, sequence length, and KV-cache behavior all move it. Quantization can also
change quality, so compare cost only at iso-quality.

Low/spiky volume adds the deployment trade-off that most SMEs actually face: either keep
the GPU warm and pay idle cost, or scale to zero and accept cold-start p99 latency.
Per-token APIs amortize warm, batched fleets across many tenants; a single org often
cannot.

  self-hosted $/1M = (gpu_$per_hr / 3600 / (agg_tok_s * utilization)) * 1e6 * ops_overhead

A 24/7 GPU bills around the clock but only earns while it's actually serving, so low
utilization is the killer: a cheap per-token API amortizes one fleet across many tenants
at near-100% utilization, which a single org rarely matches.

  python selfhosted_cost.py
  python selfhosted_cost.py --api-blended 0.05 --overhead 1.3
"""
import argparse

# ILLUSTRATIVE presets — (name, $/hr, sustained AGGREGATE decode tok/s for a ~7B model
# with a batching server). These vary hugely with engine, quantization, batch shape,
# sequence length, and quality target. MEASURE yours and edit this list; the point is
# the framework below.
GPUS = [
    ("L4 on-dem",     0.80,  2000),
    ("A10G on-dem",   1.00,  3500),
    ("A100 on-dem",   1.80,  8000),
    ("H100 on-dem",   3.50, 15000),
    ("A100 spot/rsv", 0.60,  8000),   # cheap GPU + high throughput: self-hosting can win
    ("L4 spot/rsv",   0.30,  2000),
]
UTILS = [0.05, 0.10, 0.25, 0.50, 0.75, 1.00]


def per_million(gpu_per_hr, agg_tok_s, util, overhead):
    return (gpu_per_hr / 3600.0 / (agg_tok_s * util)) * 1e6 * overhead


def breakeven_util(gpu_per_hr, agg_tok_s, api_per_m, overhead):
    """Utilization at which self-hosted $/1M == api_per_m. >1 means the API always wins."""
    return (gpu_per_hr / 3600.0 * 1e6 * overhead / api_per_m) / agg_tok_s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-blended", type=float, default=0.05,
                    help="Blended open-model API price, USD/1M tokens (in+out mix). The "
                         "benchmark used ~$0.04 in / $0.10 out for Qwen-2.5-7B; extraction "
                         "is input-heavy, so the effective blend is ~$0.04-0.06.")
    ap.add_argument("--overhead", type=float, default=1.3,
                    help="Multiplier for idle headroom, redundancy, and ops on top of raw compute.")
    args = ap.parse_args()
    api = args.api_blended

    print(f"Self-hosted GPU deployment sensitivity vs API ${api:.3f}/1M")
    print(f"(ops overhead x{args.overhead}; throughput ILLUSTRATIVE; not a benchmark)\n")
    head = f"{'GPU':13}{'$/hr':>6}{'tok/s':>7}  | " + " ".join(f"{int(u*100):>5}%" for u in UTILS) + "  | break-even"
    print(head); print("-" * len(head))
    for name, hr, toks in GPUS:
        cells = " ".join(f"{per_million(hr, toks, u, args.overhead):>6.2f}" for u in UTILS)
        u_star = breakeven_util(hr, toks, api, args.overhead)
        if u_star <= 1.0:
            mtok_day = toks * u_star * 86400 / 1e6
            be = f"{u_star*100:>3.0f}% util ({mtok_day:.1f} Mtok/day)"
        else:
            be = "never (API wins at any util)"
        print(f"{name:13}{hr:>6.2f}{toks:>7d}  | {cells}  | {be}")

    print("\nHow to read it")
    print("- Each cell = warm 24/7 self-hosted $/1M at that sustained utilization (GPU billed continuously,")
    print("  serving only that fraction).")
    print(f"- Break-even = the utilization where self-hosting matches the ${api:.3f}/1M API price. Below it the API is")
    print("  cheaper; above it self-hosting wins. Mtok/day = the daily token volume needed to reach that utilization.")
    print("- This excludes quality changes from quantization, cold-start latency if scaling to zero, and engineering")
    print("  time beyond the simple overhead multiplier.")
    print("- Treat this as a deployment card input, not a headline benchmark result. The measured benchmark uses")
    print("  hosted API costs; this map answers when own-GPU deployment could change the decision.")
    print("\nTakeaway (robust to the exact numbers, within reason)")
    print("- At today's ~$0.05/1M for a 7B, the API is roughly the self-hosted cost FLOOR for most orgs: providers")
    print("  amortize fully-utilized fleets you can't match. Self-hosting wins on cost only with a cheap GPU AND")
    print("  high, steady volume. At low/spiky SME volume, the per-token API is usually cheaper.")
    print("- So self-hosting's case at the 7B tier is mostly data control / residency / no rate limits / customization")
    print("  — NOT cost. Plug in your own GPU $/hr and measured tok/s above to check your situation.")
    print("- If you scale to zero, the cost line improves but p99 can degrade from GPU/model warm-up. If you keep")
    print("  the GPU warm, p99 improves but idle cost dominates low utilization.")
    print("\nCaveat: throughput here is illustrative aggregate serving throughput; measure yours at iso-quality")
    print("(vLLM/TGI, quantization, batch shape, sequence length, SLA). This is the same thesis as the rest of")
    print("the benchmark: the cheapest option depends on context.")


if __name__ == "__main__":
    main()
