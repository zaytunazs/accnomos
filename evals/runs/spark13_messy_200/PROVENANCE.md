# Provenance: spark13_200 and spark13_messy_200

- Date: 4 Nov 2026 (UTC 02:00–03:00), run on the owner's own server; results copied here unchanged (summary.json, report.md).
- Model: `muse-spark-1.3-contributor` through the hosted model's API (`--mode key`, base URL https://api.meta.ai/v1).
- Harness commit: `245aab82` (origin/main at the time), `evals/harness/run_extraction.py`.
- Command: `python -m harness.run_extraction --mode key --model muse-spark-1.3-contributor --verify
  --business-name 'Bramblewood Joinery Ltd' --concurrency 3 [--messy]`, gold set `evals/gold/receipts` (200 docs).
- Same harness settings as `glimmer_200_v2` / `glimmer_messy_200_v2` (code repairs, higher-resolution re-read and
  Verifier on). One difference: here the Verifier is the hosted model itself (key mode, the open-weights host off), where v2
  used the local open-weights model. A same-model verifier is less independent, so its agreement figure is not comparable with v2's.
- Per-case files (NNN_*.json, renders) are left on the Spark (~/spark/accnomos/idle-run/evals/runs/), as for the v2 runs.
