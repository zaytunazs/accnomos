# Handover: demo sandbox (branch claude/demo-sandbox)

Done (details in REVIEW.md): runtime `DEMO_MODE=1` + `DEMO_SECRET` per-visitor sandbox (`services/runtime/app/demo.py`,
`app/fake_graph.py`), every token dependency mapped to in-memory fakes, limits, 11 MB `/demo/graph/` uploads (nginx too);
web "Try the demo — no sign-in" (landing, Connect), demo banner + Reset/Leave, `/judges`, simulated HMRC, "Sent (demo —
not actually sent)"; docs (SECURITY, PRODUCTION, HONESTY, JUDGING, .env.example, compose). Seeding starts on first /health.

Verified: `tests/test_demo.py` 29 passed; ruff check/format clean; pyright app 0 errors; web eslint clean; e2e
`sandbox.spec.ts` both tests passed (main flow 1.8 min with the real seed; /judges passed alone after a Chrome OOM kill).

Left: the full runtime suite only ran to 861/1255 (stopped at `test_sample_books.py::test_a_second_press_while_running_or_after_is_the_same_run`,
a load-dependent race that also fails on the base commit); the whole e2e suite was not run (box OOM, load ~36); Android
"Try the demo" not built (noted in HONESTY.md). Branch not pushed (force push was refused by the permission system).

Test: `cd services/runtime && python -m pytest -q tests/test_demo.py`; e2e: build as usual, then
`E2E_SERVER_TIMEOUT_MS=900000 pnpm run e2e:test --project=desktop e2e/sandbox.spec.ts` (the override matters only on slow boxes).
