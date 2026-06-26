"""Self-hosted GPU cost track.

Turns the benchmark's "open-model cost = API sticker price" into the honest question
your reviewers will ask: at what sustained utilization does running the open model on
your OWN GPU beat paying per-token API pricing?

This is a parametric MODEL, not a measurement (we can't spin a GPU here). The throughput
numbers are ILLUSTRATIVE defaults for a ~7B model under batched serving (vLLM / TGI) —
replace them with YOUR measured aggregate tokens/sec. The contribution is the break-even
framework, not the specific figures.

  self-hosted $/1M = (gpu_$per_hr / 3600 / (agg_tok_s * utilization)) * 1e6 * ops_overhead

A 24/7 GPU bills around the clock but only earns while it's actually serving, so low
utilization is the killer: a cheap per-token API amortizes one fleet across many tenants
at near-100% utilization, which a single org rarely matches.

  python selfhosted_cost.py
  python selfhosted_cost.py --api-blended 0.05 --overhead 1.3
"""
import argparse

# ILLUSTRATIVE presets — (name, on-demand $/hr, sustained AGGREGATE decode tok/s for a
# ~7B model with a batching server). These vary hugely with engine, batch size, and
# sequence length. MEASURE yours and edit this list; the point is the framework below.
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

    print(f"Self-hosted $/1M tokens vs API ${api:.3f}/1M   (ops overhead x{args.overhead}; throughput ILLUSTRATIVE)\n")
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
    print("- Each cell = self-hosted $/1M at that sustained utilization (GPU billed 24/7, serving only that fraction).")
    print(f"- Break-even = the utilization where self-hosting matches the ${api:.3f}/1M API price. Below it the API is")
    print("  cheaper; above it self-hosting wins. Mtok/day = the daily token volume needed to reach that utilization.")
    print("\nTakeaway (robust to the exact numbers, within reason)")
    print("- At today's ~$0.05/1M for a 7B, the API is roughly the self-hosted cost FLOOR for most orgs: providers")
    print("  amortize fully-utilized fleets you can't match. Self-hosting wins on cost only with a cheap GPU AND")
    print("  high, steady volume. At low/spiky SME volume, the per-token API is usually cheaper.")
    print("- So self-hosting's case at the 7B tier is mostly data control / residency / no rate limits / customization")
    print("  — NOT cost. Plug in your own GPU $/hr and measured tok/s above to check your situation.")
    print("\nCaveat: throughput here is illustrative aggregate serving throughput; measure yours (vLLM/TGI, batch,")
    print("seq length). This is the same thesis as the rest of the benchmark: the cheapest option depends on context.")


if __name__ == "__main__":
    main()
