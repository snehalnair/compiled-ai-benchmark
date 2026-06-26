# Public Release Checklist

Use this before turning the benchmark folder into a public repo.

## Required Before Publish

- [ ] Choose a code license (`MIT` or `Apache-2.0` are the obvious candidates).
- [ ] Add a `LICENSE` file at the repo root.
- [ ] Pin dataset names, splits, versions, and licenses in the README.
- [ ] Add a dated model/price table for every reported run.
- [ ] Verify every result table can be regenerated from the committed scripts.
- [ ] Add a `.env.example` with required API variables but no secrets.
- [ ] Confirm no provider keys, raw private docs, or cached secrets are committed.
- [ ] Mark all latency numbers as provider-measured and load-dependent.
- [ ] Keep `RESULTS.md` as the evidence log and `WRITEUP.md` as the public narrative.

## Nice To Have

- [ ] Add `make smoke`, `make sweep-invoices`, `make sweep-triage`, and `make harden`.
- [ ] Add a tiny offline unit test for scoring, disagreement, and majority vote.
- [ ] Add a `CITATION.cff` once the project name stabilizes.
- [ ] Add CSV schema notes for the files under `data/`.
- [ ] Add a workflow-card example: spec, eval, route topology, cost profile, latency
      profile, and drift checks.

## Suggested Release Shape

1. Publish the benchmark repo with `README.md`, `RESULTS.md`, `WRITEUP.md`, scripts,
   requirements, and CSV outputs.
2. Publish the essay separately, linking to the benchmark as the evidence artifact.
3. Invite one external replication on a new task before claiming generality beyond
   extraction and classification.
