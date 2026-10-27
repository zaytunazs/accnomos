# Review: `claude/lint-followup`

Task: `TASK_BRIEF.md`. This branch clears the leftover ruff findings, and the only code changes are the lint fixes.

## What was checked

- `ruff check .` and `ruff format --check .` (ruff 0.17.3, the version `lint.yml` pins): **All checks passed**, 264 files formatted.
  The brief's `services evals tools packages` roots are a subset of `.`.
- `pyright` 1.1.414 (basic, scope from `pyproject.toml`): 2 errors, both in `services/runtime/app/invoicing.py`
  (`:135` `default_factory=BankDetails`, `:408` `InvoiceCustomer(...)` "missing email, vrn"). A clean `origin/main` worktree
  reports the **same 2 errors**, so this branch did not introduce them (see "What remains").
- Tests, all green: `services/runtime` 815 passed, 1 skipped; `services/hmrc-relay` 102; `packages/ledger` 35;
  `packages/connectors` 43; `evals` 158.
- Strings unchanged: an AST comparison against `origin/main` (adjacent string parts folded together) shows each wrapped
  file is AST-identical: `replay.py`, `report_200.py`, `approve.py`, `test_supplier_vat.py`, `seed_demo.py`. The only
  differences are the intended ones:
  - `invoicing.py`: B023 (`got` bound as a default argument; `_update_json` calls `bump(seq)` with one argument, so this
    is equivalent) and SIM105 (`contextlib.suppress(FileExistsError)`).
  - `repair.py`: B905 `strict=True` (`incl` is built from `doc.lines` and `split` from `incl`, so the lengths always
    match) and SIM102 (the nested `if` collapsed into one condition with the same logic).
  - `pipeline.py`: the module docstring, reflowed.
- Product rules: nothing touches storage, AI or user data, and no pence or decimal logic changed. Web files are unchanged,
  so there was no web build to run.

## What I fixed

- `3d9bc4f` tests: the three `TOTALS_REPAIRED` messages and the personal-vehicle `ApprovalError` are now asserted
  word for word, so a future re-wrap can't change them silently. There is also a new test for the
  `contextlib.suppress` path: voiding after the reversal was already posted finishes without posting it twice.
- `43e52b3` the `pipeline.py` docstring is wrapped instead of hidden behind `# noqa: E501`. Fragmented f-string splits in
  `report_200.py` (`"covering "`, `"issued "`…) and `seed_demo.py` are reflowed; both files are still AST-identical to main.

## What remains

- pyright reports 2 errors in `services/runtime/app/invoicing.py` (lines 135 and 408) in this environment. They are also
  on `origin/main` and are not caused by this branch. I could not confirm whether CI's `uv sync --frozen` venv shows them
  too (I didn't check the CI run history). If `lint.yml` fails on pyright, fix them separately: use
  `default_factory=lambda: BankDetails()` and pass `email=None, vrn=None` explicitly.
- Brief item 3 ("lint.yml green on the first push") is not proven: nothing was pushed. Locally, ruff check and format
  are green; for pyright, see the item above.
- Some brief-listed files (`contacts.py`, `checks.py`, `test_seed_demo.py`, `test_checks_journal.py`) have no changes on
  this branch. They already pass ruff here, so their findings were presumably fixed on main before this branch.
- `7b36949` is a "wip: checkpoint" commit that only adds `TASK_BRIEF.md`. Squash it or drop it before merging if the
  brief file shouldn't land on main.

## How to verify by hand

From the repo root run `uvx ruff@0.17.3 check .` and `uvx ruff@0.17.3 format --check .`; both should be clean. Then run
`uv sync --frozen --package accnomos-runtime && uvx pyright@1.1.414 --pythonpath .venv/bin/python`; expect 0 errors,
or the same 2 that `origin/main` gives. Next run `pytest -q` in `services/runtime`, `services/hmrc-relay`,
`packages/ledger`, `packages/connectors` and `evals`. Finally run `git diff origin/main...HEAD` and check that each hunk is
either a pure re-wrap of an implicitly concatenated string or one of the four rule fixes listed above. For a quick
behaviour check of the reworded messages, run `pytest -q services/runtime/tests/test_repair.py -k worded`.
