"""v2 — harden invoices: n>=100, continuous ensemble-confidence gate, latency (p50/p99),
and an upfront-router arm. Reports the cost x quality x LATENCY frontier.

One measurement pass per doc runs a 3-model cheap ensemble (OPEN_MODEL/_2/_3) + the
frontier, recording predictions, correctness, per-call latency and cost. From it we derive:
  - Ensemble       : cheap 3-model majority vote (the cheap floor).
  - Cascade(tau)   : majority vote; escalate to frontier when vote-agreement confidence
                     < tau. Sweep tau -> smooth Pareto curve. Accurate gate (sees outputs),
                     but escalated docs pay cheap+frontier sequentially -> high tail latency.
  - Upfront(theta) : a fast logistic gate on INPUT-ONLY features (no LLM, cross-fitted)
                     predicts whether the cheap path will fail and routes to ONE model ->
                     frontier-level tail latency, at the cost of a blinder gate.
  - Frontier       : the quality ceiling.

Latency is MODELED from measured component latencies: the 3 cheap calls are assumed issued
in parallel (cheap leg = max of the three); cascade escalation adds the frontier leg
sequentially; the upfront gate is ~1 ms. API latencies are measured under concurrent load,
so treat them as indicative and read the RELATIVE tail behaviour, not absolute ms.

  python harden.py --limit 100 --workers 6
  python harden.py --task tasks/example_triage.yaml --limit 100 --workers 6
"""
import argparse
import csv
import math
import os
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import arms
import clients
import config
import loaders
import scoring
from run import bootstrap_ci, check_keys

CHEAP = [config.OPEN_MODEL, config.OPEN_MODEL_2, config.OPEN_MODEL_3]
GATE_LATENCY_S = 0.001  # logistic eval on input features


def features(text):
    toks = text.split()
    return [len(text),
            sum(c.isdigit() for c in text),
            sum(1 for t in toks if len(t) >= 12),     # long alnum tokens (IBAN-like)
            sum(1 for c in text if c.isupper()),
            text.count("\n"),
            text.count("/") + text.count("-")]


def majority(preds, fields):
    """Per-field majority vote across the ensemble + an agreement confidence in [1/M, 1]."""
    m = len(preds)
    vote, conf_sum = {}, 0.0
    for k in fields:
        normed = [scoring._norm_str(p.get(k)) if p else "" for p in preds]
        best, cnt = Counter(normed).most_common(1)[0]
        conf_sum += cnt / m
        vote[k] = next((p.get(k) for p in preds if p and scoring._norm_str(p.get(k)) == best), None)
    return vote, conf_sum / len(fields)


def collect(doc, task):
    preds, cheap_lat, cheap_cost = [], [], 0.0
    for model in CHEAP:
        r = clients.call_open(arms._system(task), arms._user(doc["text"]), model=model, max_tokens=512)
        preds.append(scoring.extract_json(r.text))
        cheap_lat.append(r.usage.latency_s)
        cheap_cost += r.usage.cost_usd
    rf = clients.call_frontier(arms._system(task), arms._user(doc["text"]), thinking=False,
                               max_tokens=512, json_schema=arms._schema(task))
    pf = scoring.extract_json(rf.text)
    vote, conf = majority(preds, task.fields)
    sc = lambda p: scoring.score(p, doc["fields"], task.fields, task.numeric_fields)["exact_doc"]
    return {"vote_correct": sc(vote), "frontier_correct": sc(pf), "conf": conf,
            "cheap_cost": cheap_cost, "frontier_cost": rf.usage.cost_usd,
            "cheap_leg_lat": max(cheap_lat), "frontier_lat": rf.usage.latency_s,
            "feat": features(doc["text"])}


def fit_logistic(X, y, iters=3000, lr=0.3):
    X = np.array(X, float); y = np.array(y, float)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    if len(set(y)) < 2:                       # degenerate: predict the constant base rate
        base = float(y.mean())
        return lambda Xt: np.full(len(Xt), base)
    w = np.zeros(Xs.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xs @ w))
        w -= lr * (Xs.T @ (p - y)) / len(y)
    return lambda Xt: 1 / (1 + np.exp(-np.hstack([np.ones((len(Xt), 1)), (np.array(Xt, float) - mu) / sd]) @ w))


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0.0
    return s[min(len(s) - 1, max(0, math.ceil(q / 100 * len(s)) - 1))]


def summarize(name, per_doc, b_cost, seed):
    succ = bootstrap_ci([r["success"] for r in per_doc], seed=seed)
    cost = statistics.mean(r["cost"] for r in per_doc)
    return {"name": name, "succ": succ, "cost": cost,
            "f": statistics.mean(r["frontier"] for r in per_doc),
            "p50": pct([r["lat"] for r in per_doc], 50) * 1000,
            "p99": pct([r["lat"] for r in per_doc], 99) * 1000,
            "xb": (b_cost / cost) if cost else float("nan")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--task", help="YAML task spec. Defaults to hard invoice task.")
    args = ap.parse_args()
    check_keys(["B_frontier_singleshot", "D_compiled_open"])

    task = (loaders.load_yaml_task(args.task, limit=args.limit, seed=args.seed)
            if args.task else loaders.load_invoices_ocr(limit=args.limit, seed=args.seed, hard=True))
    print(f"dataset={task.name}  fields={task.fields}  n={len(task.samples)}")
    print(f"ensemble={CHEAP}  frontier={config.FRONTIER_MODEL}")
    print("measuring (3 cheap + frontier per doc) ...")

    def safe(d):
        try:
            return collect(d, task)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        out = list(ex.map(safe, task.samples))
    recs = [r for r in out if r]
    n = len(recs)
    if n < len(out):
        print(f"  ({len(out) - n} docs dropped after retries)")
    b_cost = statistics.mean(r["frontier_cost"] for r in recs)
    front_success = statistics.mean(r["frontier_correct"] for r in recs)

    # cross-fitted upfront-gate predictions (out-of-fold), so every doc is evaluable
    rng = np.random.RandomState(args.seed)
    order = rng.permutation(n)
    foldA, foldB = order[: n // 2], order[n // 2:]
    upfront_p = np.zeros(n)
    for train_idx, test_idx in ((foldA, foldB), (foldB, foldA)):
        predict = fit_logistic([recs[i]["feat"] for i in train_idx],
                               [1 - recs[i]["vote_correct"] for i in train_idx])  # 1 = cheap fails
        upfront_p[test_idx] = predict([recs[i]["feat"] for i in test_idx])

    def cascade_point(tau):
        rows = []
        for r in recs:
            esc = r["conf"] < tau
            rows.append({"success": r["frontier_correct"] if esc else r["vote_correct"],
                         "cost": r["cheap_cost"] + (r["frontier_cost"] if esc else 0),
                         "lat": r["cheap_leg_lat"] + (r["frontier_lat"] if esc else 0),
                         "frontier": 1 if esc else 0})
        return rows

    def upfront_point(theta):
        rows = []
        for i, r in enumerate(recs):
            route_fr = upfront_p[i] >= theta
            rows.append({"success": r["frontier_correct"] if route_fr else r["vote_correct"],
                         "cost": r["frontier_cost"] if route_fr else r["cheap_cost"],
                         "lat": GATE_LATENCY_S + (r["frontier_lat"] if route_fr else r["cheap_leg_lat"]),
                         "frontier": 1 if route_fr else 0})
        return rows

    # endpoints
    ensemble = summarize("Ensemble (3 cheap, vote)",
                         [{"success": r["vote_correct"], "cost": r["cheap_cost"],
                           "lat": r["cheap_leg_lat"], "frontier": 0} for r in recs], b_cost, args.seed)
    frontier = summarize("Frontier only",
                         [{"success": r["frontier_correct"], "cost": r["frontier_cost"],
                           "lat": r["frontier_lat"], "frontier": 1} for r in recs], b_cost, args.seed)

    # full sweeps (for CSV) + knee = cheapest point reaching frontier parity (within 1 pt)
    def sweep(builder, grid):
        pts = [summarize("", builder(t), b_cost, args.seed) for t in grid]
        return pts

    casc_grid = sorted(set(r["conf"] for r in recs) | {0.0, 1.01})
    upf_grid = sorted(set(upfront_p.tolist()) | {-0.01, 1.01})
    casc_pts = sweep(cascade_point, casc_grid)
    upf_pts = sweep(upfront_point, upf_grid)

    def knee(pts):
        ok = [p for p in pts if p["succ"][0] >= front_success - 0.01]
        return min(ok, key=lambda p: p["cost"]) if ok else min(pts, key=lambda p: -p["succ"][0])

    casc_knee = knee(casc_pts); casc_knee["name"] = "Cascade @ parity"
    upf_knee = knee(upf_pts);   upf_knee["name"] = "Upfront @ parity"

    rows = [ensemble, casc_knee, upf_knee, frontier]
    print("\n" + "=" * 104)
    hdr = f"{'operating point':26}{'success [95% CI]':>22}{'cost/run':>11}{'xB':>7}{'front%':>8}{'p50 ms':>9}{'p99 ms':>9}"
    print(hdr); print("-" * 104)
    for r in rows:
        s = r["succ"]
        print(f"{r['name']:26}{f'{s[0]:.2f} [{s[1]:.2f}-{s[2]:.2f}]':>22}"
              f"{'$' + format(r['cost'], '.5f'):>11}{f'{r['xb']:.1f}x':>7}"
              f"{r['f']:>7.0%}{r['p50']:>9.0f}{r['p99']:>9.0f}")
    print("=" * 104)
    print(f"\nn={n} · frontier parity = {front_success:.2f} success · latency modeled (cheap leg = parallel max;")
    print("cascade escalation adds frontier leg sequentially; upfront gate ~1ms). Read the tail (p99):")
    print("cascade is cheapest at parity but its tail stacks; upfront trades a little cost/quality for a flat tail.")

    out = os.path.join(os.path.dirname(__file__), "data", "harden_invoices_frontier.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["method", "tau_or_theta", "success", "cost_per_run", "frontier_fraction", "p50_ms", "p99_ms"])
        for t, p in zip(casc_grid, casc_pts):
            w.writerow(["cascade", f"{t:.4f}", f"{p['succ'][0]:.4f}", f"{p['cost']:.6f}", f"{p['f']:.4f}", f"{p['p50']:.1f}", f"{p['p99']:.1f}"])
        for t, p in zip(upf_grid, upf_pts):
            w.writerow(["upfront", f"{t:.4f}", f"{p['succ'][0]:.4f}", f"{p['cost']:.6f}", f"{p['f']:.4f}", f"{p['p50']:.1f}", f"{p['p99']:.1f}"])
    print(f"saved full cost/quality/latency sweeps -> {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
