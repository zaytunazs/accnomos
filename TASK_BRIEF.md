# Task: Lint follow-up — clear the 53 ruff findings left after the lint pass merged over newer files, keep lint.yml green

Accnomos monorepo (public; UK English). `ruff check services evals tools packages` on main reports 53 findings: 46 E501 (long lines in
`evals/harness/report_200.py`, `services/runtime/tests/test_supplier_vat.py`, `app/contacts.py`, `tools/seed_demo.py`,
`tests/test_seed_demo.py`, `app/repair.py`, `app/checks.py`, `app/pipeline.py`, `app/approve.py`, `tests/test_checks_journal.py`),
3 B905 (`zip()` in `app/repair.py` — decide `strict=True` only where lengths are guaranteed equal; otherwise `strict=False` with a
comment), 1 B023 (`app/invoicing.py:369`, a closure over a loop variable — bind it), 1 SIM105, 1 SIM102, 1 E402 (`tools/seed_demo.py`
imports after `sys.path` tweak — keep with a `# noqa: E402  sys.path first` reason).

## Deliverables
1. Zero findings from `ruff check` and `ruff format --check` on those four roots; strings byte-identical when wrapping (tests prove it).
2. `pyright` basic still clean on `services/runtime/app` and `packages/*/src`.
3. `.github/workflows/lint.yml` green on the first push (read it; run the same commands locally).
4. All test suites green (`pytest` in services/runtime, services/hmrc-relay, packages, evals).
No behaviour changes. Commit in small steps; do not push. Finish with `git log --oneline -8` and the before/after counts.
