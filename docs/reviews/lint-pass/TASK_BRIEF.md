# Task: Lint and type pass across the repo (ruff, pyright/mypy-lite on the runtime, tsc strict, dart analyze already green) — fix, don't silence

Accnomos monorepo (public; UK English). Every review today says "ruff was not run". Read first `pyproject.toml` files (ruff config, if any),
`services/runtime`, `services/hmrc-relay`, `packages/*`, `evals/harness`, `tools/*.py`, `apps/web/tsconfig.json`, `.github/workflows/*.yml`.

## Deliverables
1. Add a repo-level `ruff` config (line length 120, target py312, rules: E, F, I, B, UP, SIM; per-file ignores only where justified in a
   comment) and run `ruff check --fix` + `ruff format --check` across all Python. Fix real findings by hand (unused imports, shadowed
   names, mutable defaults, bare excepts that swallow, f-strings without placeholders). No `# noqa` without a reason.
2. Type check: `pyright` (basic mode) on `services/runtime/app` and `packages/*/src`; fix genuine type errors (Optional handling,
   wrong return types); add `py.typed` where missing. Keep behaviour identical; tests must stay green (`pytest` in all four places,
   evals tests too).
3. Web: `tsc --noEmit` is already part of the build; add `"noUncheckedIndexedAccess": true` if it finds fewer than ~30 issues and fix
   them, else leave it and say so.
4. CI: a `lint.yml` workflow (ruff + pyright + eslint + tsc) under 2 minutes with caches; `docs/DEV.md` gets the one-liner to run it locally.
Commit in small steps; do not push. Finish with `git log --oneline -8` and the counts before/after per tool.
