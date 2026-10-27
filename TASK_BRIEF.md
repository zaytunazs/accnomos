# Task: Autopilot L2 safety eval — simulate rule-based posting over the seeded books and the 200-doc set; measure false posts

Accnomos monorepo (public; UK English; no secrets; Glimmer on Ollama :11434 for any model call). Read first `services/runtime/app/autopilot.py`,
`app/rules.py` (or wherever saved rules live), `app/pipeline.py`, `app/ai/verify.py`, `docs/AUTOPILOT.md`, `docs/reviews/autopilot-rules/REVIEW.md`,
`docs/reviews/verifier/REVIEW.md`, `tools/seed_demo.py` (the fictional company's plan), `evals/gold/*`, `evals/harness/*`.

## Deliverables
1. `evals/harness/autopilot_sim.py`: builds the seeded books in memory (fake storage), saves the rules the demo user would plausibly
   save (same supplier + VAT + treatment, from the posted history), then feeds the 25 inbox documents and the 200-doc set through the
   real pipeline at L2 with the verifier on (Glimmer reading twice with different prompts, as the demo does) and off. Records per document:
   would-post / proposed / needs-a-look, and against gold: correct post, **false post** (posted but a field differs from gold or the
   document was a duplicate/needs-a-look), missed post. No code path may be stubbed except the model backend selection.
2. `evals/runs/autopilot_l2/report.md` + JSON: false-post rate with and without the verifier, by document class (clean / messy /
   handwritten / duplicate / no-VRN), the ≤2× total rule's effect, time per document. The headline must be the false-post rate.
3. If the false-post rate with the verifier on is above 1 % on clean documents, tighten `autopilot.py` (never loosen) and re-run;
   each tightening is a separate commit with the before/after numbers. Existing tests stay green.
4. `docs/AUTOPILOT.md` and the README Autopilot row quote the numbers and the exact command to reproduce them.
Commit in small steps; do not push. Finish with `git log --oneline -8` and the headline numbers.
