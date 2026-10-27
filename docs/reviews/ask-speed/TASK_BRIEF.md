# Task: Ask speed and grounding — no 120 s timeouts on Glimmer, period-aware grounding, streaming the explanation

Accnomos monorepo (public; UK English; no secrets; Glimmer on Ollama :11434). Read first `evals/runs/ask_40/report.md` (4/35 Glimmer
timeouts; grounding cannot catch a real figure from the wrong period), `services/runtime/app/facts.py`, `app/ai/ask.py`, `app/routes_ask.py`,
`app/schemas.py` (`AskAnswer`), `apps/web/src/components/ask/*`, `apps/mobile/lib/screens/ask_screen.dart` (read only), `evals/harness/ask_eval.py`.

## Deliverables
1. **Facts pack size**: measure tokens per question on the seeded books; cap the pack at a budget (e.g. 3k tokens) by sending only the
   sections the question needs (a cheap code router on keywords: VAT, invoices, bank, jobs, payroll, deadlines, contacts) plus the
   always-on summary. Record before/after sizes and answer times in `evals/runs/ask_40/report.md`.
2. **Period-aware grounding**: every key number in the facts carries its period; a figure in the model's answer that matches a fact
   from a *different* period than the one asked about is flagged and replaced like an invented one, with the citation pointing at the
   right period. Tests with a planted wrong-period figure.
3. **Streaming**: `POST /books/ask` gains `?stream=1` (SSE): first event = key numbers and citations from code (instant), then the
   explanation tokens, final event = the checked answer object (same shape as today). The web Ask uses it (falls back to the plain
   call); Android keeps the plain call. Timeout per token, not per answer.
4. Re-run the 40-question eval on Glimmer: timeouts must be 0; exact/cited/no-invented unchanged or better. README Ask row updated.
Commit in small steps; do not push. Finish with `git log --oneline -8` and the before/after table.
