"""v1 benchmark runner: pluggable dataset, parallel execution, bootstrap CIs.

  python run.py                                   # invoices_ocr, 40 docs, arms B/D/R
  python run.py --dataset synthetic --limit 6
  python run.py --arms A,B,D,R --limit 60 --workers 8

Table columns: success [95% CI] · field_acc · cost/run · xB · frontier-fraction f
"""
import argparse
import os
import random
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

import arms
import config
import loaders
import scoring


def bootstrap_ci(vals, fn=statistics.mean, n=2000, seed=0, alpha=0.05):
    if not vals:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    point = fn(vals)
    boots = sorted(fn([vals[rng.randrange(len(vals))] for _ in vals]) for _ in range(n))
    return (point, boots[int((alpha / 2) * n)], boots[int((1 - alpha / 2) * n) - 1])


def check_keys(selected):
    need_frontier = any(a.startswith(("A_", "B_", "R_")) for a in selected)
    need_open = any(a.startswith(("D_", "R_")) for a in selected)
    missing = []
    if need_frontier and not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY  (frontier arms A/B/R)")
    if need_open and not config.OPEN_API_KEY:
        missing.append("OPENROUTER_API_KEY/OPEN_API_KEY + OPEN_BASE_URL + OPEN_MODEL  (open arms D/R)")
    if missing:
        print("Missing required configuration:\n  - " + "\n  - ".join(missing))
        sys.exit(1)


def run_arm(arm_name, task, workers):
    fn = arms.ARMS[arm_name]

    def one(s):
        try:
            pred, usages, route = fn(s["text"], task)
            sc = scoring.score(pred, s["fields"], task.fields, task.numeric_fields)
            return {"exact_doc": sc["exact_doc"], "field_accuracy": sc["field_accuracy"],
                    "cost": sum(u.cost_usd for u in usages), "route": route}
        except Exception as e:
            return {"exact_doc": 0, "field_accuracy": 0.0, "cost": 0.0, "route": "error", "err": str(e)}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, task.samples))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="invoices_ocr", choices=list(loaders.LOADERS))
    ap.add_argument("--arms", default="B_frontier_singleshot,D_compiled_open,R_routed_cascade")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    selected = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in selected:
        if a not in arms.ARMS:
            print(f"Unknown arm {a!r}. Available: {', '.join(arms.ARMS)}")
            sys.exit(1)
    check_keys(selected)

    print(f"Loading dataset '{args.dataset}' (limit {args.limit}) ...")
    task = loaders.LOADERS[args.dataset](limit=args.limit, seed=args.seed)
    print(f"dataset={task.name}  fields={task.fields}  n={len(task.samples)}  "
          f"arms={selected}  prices_as_of={config.PRICES_AS_OF}\n")

    results = {}
    for a in selected:
        results[a] = run_arm(a, task, args.workers)
        errs = sum(1 for r in results[a] if r["route"] == "error")
        msg = f"  done: {a}" + (f"  ({errs} errors)" if errs else "")
        if errs:
            msg += "  e.g. " + next(r.get("err", "") for r in results[a] if r["route"] == "error")[:80]
        print(msg)

    b_cost = (statistics.mean([r["cost"] for r in results["B_frontier_singleshot"]])
              if "B_frontier_singleshot" in results else None)

    print("\n" + "=" * 100)
    print(f"{'arm':24}{'success [95% CI]':>28}{'field_acc':>11}{'cost/run':>12}{'xB':>7}{'front_frac':>12}")
    print("-" * 100)
    for a in selected:
        rows = results[a]
        succ = bootstrap_ci([r["exact_doc"] for r in rows], seed=args.seed)
        facc = statistics.mean([r["field_accuracy"] for r in rows])
        cost = statistics.mean([r["cost"] for r in rows])
        f_frac = statistics.mean([1 if r["route"] in ("frontier", "escalated") else 0 for r in rows])
        xb = f"{b_cost / cost:5.1f}x" if (b_cost and cost) else "  -- "
        succ_s = f"{succ[0]:.2f} [{succ[1]:.2f}-{succ[2]:.2f}]"
        print(f"{a:24}{succ_s:>28}{facc:>11.2f}{'$' + format(cost, '.5f'):>12}{xb:>7}{f_frac:>11.0%}")
    print("=" * 100)
    print(f"\nn={len(task.samples)} · success=all-fields-correct (95% bootstrap CI) · cost/run=mean USD/doc")
    print("xB=times cheaper than arm B at iso-quality · front_frac=fraction routed to frontier (H6)")


if __name__ == "__main__":
    main()
