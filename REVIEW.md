# Review: `claude/lint-pass-2`

Brief: `TASK_BRIEF.md` (lint and type pass: ruff, pyright basic, tsc / `noUncheckedIndexedAccess`, `lint.yml` CI).

## What I found

The implement pass committed only `TASK_BRIEF.md` (b1fd5e2, "wip: checkpoint"). No lint, type or CI work was on the
branch, so the review pass did the brief itself, in small commits, keeping behaviour identical.

## What was checked

- `pytest -q` in all five places, before and after every step: packages/ledger 35, packages/connectors 43,
  services/runtime 764 + 1 skipped (ffmpeg case), services/hmrc-relay 102, evals 158 (+1 new runtime fixture case).
  All green at the start and at the end.
- `ruff check .`, `ruff format --check .` (ruff 0.17.3), `pyright` 1.1.414 (basic) on `services/runtime/app` and
  `packages/*/src`, `eslint .` and `tsc --noEmit` in `apps/web`.
- No web files changed, so `pnpm run build` was not re-run (`tsc --noEmit` and eslint pass).
- Long-line wrapping in prompts and strings was verified by comparing each file's AST before and after (adjacent literals
  join at parse time): every string value, including model prompts, is byte-identical. Only docstrings differ.

## Counts before → after

| Tool | Before | After |
|---|---|---|
| ruff check (E, F, I, B, UP, SIM; 120 cols) | 1047 | 0 |
| ruff format --check | 132 files to reformat | 0 |
| pyright basic | 90 errors | 0 |
| eslint (apps/web) | 0 | 0 |
| tsc --noEmit (apps/web) | 0 | 0 |
| tsc with `noUncheckedIndexedAccess` | 95 | not enabled (over the brief's ~30 limit) |

## What I fixed (commits)

- **2cc036e** Repo ruff config in the root `pyproject.toml` (120 cols, py312, E/F/I/B/UP/SIM) and `ruff format` over
  all Python. Mechanical only; a candidate for `.git-blame-ignore-revs`.
- **b1bdd87** `ruff --fix`: import order, unused imports, and duplicate import blocks left by keep-both merges
  (`accnomos_connectors/__init__.py`, `routes_vat.py`). FastAPI `Depends`/`File`/`Query` and the frozen `VatCycle` are
  declared immutable calls for B008, with the reason given in a comment. There are no per-file ignores.
- **a5dc0e7** Hand fixes:
  - `invoicing.allocate_number` no longer defines a closure per loop pass (B023).
  - Removed a second, identical `reversal()` helper in `test_vat.py` (F811).
  - Neighbour checks use `itertools.pairwise`, and other `zip` calls state `strict=` explicitly.
  - `main.py` has a single `app.ai.config` import (E402).
  - Applied `contextlib.suppress`, merged nested ifs, and renamed `l` to `ln`.
  - The three `conftest.py` files lost their duplicated docstrings and `sys.path` blocks (merge leftovers).
- **56df204** pyright clean (90 → 0), plus `py.typed` in both packages:
  - Positional `Field(x, …)` is now `Field(default=x, …)`. This fixed about 30 false "argument missing" errors and
    changes no behaviour.
  - `LENIENT` is now a `TypedDict`.
  - Optional values are handled explicitly in the projection workbook, the `routes_vat` receipt spans and `actions`
    `customer_ref`.
  - Types are more precise: `detect_bank -> BankName`, `_payment_method -> PaymentMethod`,
    `allowances(claimed: AbstractSet[str])`.
  - The `ai/config` `Request` fallback is now split under `TYPE_CHECKING`.
  - One `# pyright: ignore[reportAssignmentType]` with a reason sits on the deliberate `journal.py` `VatCode` fallback.
- **1ebce8b**, **3abfc7f** E501 wrapping in `evals/`, `tools/`, `services/` and `packages/`, with strings byte-identical.
- **f14d6d7** `.github/workflows/lint.yml`: two parallel jobs.
  - Python: ruff check, ruff format, `uv sync`, then pyright.
  - Web: pnpm install, eslint, tsc.
  - Uses the uv and pnpm caches and pins ruff and pyright versions.
  - `docs/DEV.md` gets a "Lint and type checks" one-liner.
- **5754ec7** Test fixture: a hand-edited VAT receipt whose period is not an object is skipped.

## What remains

- `lint.yml` has not been run on GitHub (no push). The under-2-minutes claim is an estimate: ruff takes seconds, and
  pyright plus `uv sync` should take about 30–60 s warm. Confirm on the first PR run.
- The runtime reads user files with `model_validate(..., extra="ignore")` (`**LENIENT`), which appears to need a newer
  Pydantic than the declared `pydantic>=2.9`. `uv.lock` pins 2.14.1, so CI and Docker are fine, but the lower bound
  should probably be raised. That change needs `uv lock`, which was not available here, so I left it.
- `noUncheckedIndexedAccess` was left off (95 errors). Enabling it is a separate task.
- `ruff format` touched 132 files. Branches open at the same time will conflict on formatting. Rebasing and re-running
  `ruff format` resolves it. Consider adding 2cc036e to `.git-blame-ignore-revs`.
- The OpenAPI description for `POST /books/scan` now contains a line break (rewrapped docstring). It is cosmetic.
- The ruff config adds isort `known-first-party` for the workspace packages, so `accnomos_*` imports now group with
  `app`. This is a style choice, easy to drop.

## How to verify by hand

1. From the repo root, run `uvx ruff@0.17.3 check .` and `uvx ruff@0.17.3 format --check .`. Both should be clean.
2. Run `uv sync --all-packages --all-extras`, then `uvx pyright@1.1.414 --pythonpath .venv/bin/python`. It should
   report 0 errors.
3. Run `uv run pytest -q` (or `python -m pytest -q services/runtime/tests` and then the other four test directories).
   Expect 765 + 338 passing (1 skipped without ffmpeg).
4. In `apps/web`, run `pnpm run lint` and `pnpm exec tsc --noEmit`.
5. To check that nothing behavioural moved, run `git diff origin/main...HEAD -- services/runtime/app` and skim the
   non-whitespace changes: they are listed under 56df204 and a5dc0e7 above.
6. Open a PR and watch the "Lint and types" workflow time itself.
