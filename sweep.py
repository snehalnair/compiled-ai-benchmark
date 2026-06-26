"""v1.2 — disagreement-gate router, swept for a cost–quality Pareto curve.

Gate: run two cheap open models (OPEN_MODEL, OPEN_MODEL_2); count the fields they
disagree on; escalate to the frontier when disagreement >= T. Sweeping T traces the
Pareto frontier between the all-open endpoint (cheap, lower quality) and the
all-frontier endpoint (expensive, top quality).

One measurement pass runs both cheap models + the frontier on EVERY doc, so we can
compute every threshold's realistic cost/quality without re-calling. (In production
the router would call the frontier only on escalated docs; the per-row cost below
already reflects that — frontier cost is added only when d >= T.)

  python sweep.py --limit 50 --hard
"""
import argparse
import csv
import os
import statistics
from concurrent.futures import ThreadPoolExecutor

import arms
import clients
import config
import loaders
import scoring
from run import bootstrap_ci, check_keys


def collect(doc, task):
    sysmsg, schema, user = arms._system(task), arms._schema(task), arms._user(doc["text"])
    r1 = clients.call_open(sysmsg, user, model=config.OPEN_MODEL)
    r2 = clients.call_open(sysmsg, user, model=config.OPEN_MODEL_2)
    rf = clients.call_frontier(sysmsg, user, thinking=False, max_tokens=512, json_schema=schema)
    p1, p2, pf = (scoring.extract_json(r.text) for r in (r1, r2, rf))
    sc = lambda p: scoring.score(p, doc["fields"], task.fields, task.numeric_fields)["exact_doc"]
    return {"c1": sc(p1), "cf": sc(pf),
            "d": scoring.disagreement(p1, p2, task.fields, task.numeric_fields),
            "cost1": r1.usage.cost_usd, "cost2": r2.usage.cost_usd, "costf": rf.usage.cost_usd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dataset", default="invoices_ocr", choices=list(loaders.LOADERS))
    ap.add_argument("--hard", action="store_true")
    args = ap.parse_args()
    check_keys(["B_frontier_singleshot", "D_compiled_open"])  # need frontier + open

    if args.dataset == "invoices_ocr":
        task = loaders.load_invoices_ocr(limit=args.limit, seed=args.seed, hard=args.hard)
    else:
        task = loaders.LOADERS[args.dataset](limit=args.limit, seed=args.seed)
    print(f"dataset={task.name}  fields={task.fields}  n={len(task.samples)}")
    print(f"open1={config.OPEN_MODEL}  open2={config.OPEN_MODEL_2}  frontier={config.FRONTIER_MODEL}\n")
    print("measuring (both cheap models + frontier on every doc) ...")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        recs = list(ex.map(lambda d: collect(d, task), task.samples))

    nf = len(task.fields)
    b_cost = statistics.mean(r["costf"] for r in recs)

    def point(name, succ, cost, frac):
        return {"name": name, "succ": bootstrap_ci(succ, seed=args.seed),
                "cost": statistics.mean(cost), "f": statistics.mean(frac)}

    rows = [point("D open1-only", [r["c1"] for r in recs], [r["cost1"] for r in recs], [0] * len(recs))]
    for T in range(nf, 0, -1):  # higher T = less escalation; decreasing T walks toward frontier
        rows.append(point(
            f"R disagree>={T}",
            [(r["cf"] if r["d"] >= T else r["c1"]) for r in recs],
            [(r["cost1"] + r["cost2"] + (r["costf"] if r["d"] >= T else 0)) for r in recs],
            [(1 if r["d"] >= T else 0) for r in recs]))
    rows.append(point("B frontier-only", [r["cf"] for r in recs], [r["costf"] for r in recs], [1] * len(recs)))

    print("\n" + "=" * 86)
    print(f"{'operating point':22}{'success [95% CI]':>27}{'cost/run':>12}{'xB':>8}{'front_frac':>12}")
    print("-" * 86)
    for row in rows:
        s = row["succ"]
        xb = f"{b_cost / row['cost']:5.1f}x" if row["cost"] else "   -- "
        print(f"{row['name']:22}{f'{s[0]:.2f} [{s[1]:.2f}-{s[2]:.2f}]':>27}"
              f"{'$' + format(row['cost'], '.5f'):>12}{xb:>8}{row['f']:>11.0%}")
    print("=" * 86)
    print(f"\nn={len(task.samples)} · escalate when the two cheap models disagree on >= T fields")
    print("Read the knee: the cheapest R-point whose CI overlaps B's success is the operating point.")

    out = os.path.join(os.path.dirname(__file__), "data", f"pareto_{task.name}.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["point", "success", "success_lo", "success_hi", "cost_per_run", "frontier_fraction"])
        for row in rows:
            w.writerow([row["name"], f"{row['succ'][0]:.4f}", f"{row['succ'][1]:.4f}",
                        f"{row['succ'][2]:.4f}", f"{row['cost']:.6f}", f"{row['f']:.4f}"])
    print(f"saved Pareto points -> {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
