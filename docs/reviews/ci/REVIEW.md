# Review: GitHub Actions CI (`claude/ci`, 28 Oct 2026)

**Green run:** [CI #2, run 40634724575](https://github.com/zaytunazs/accnomos/actions/runs/40634724575) on `d501339`:
10 of 10 jobs passed, 6 min 29 s wall clock. The first run ([40632307315](https://github.com/zaytunazs/accnomos/actions/runs/40632307315),
`84d049f`) had 8 of 10 green; both failures are explained below and fixed.

## What runs

`.github/workflows/ci.yml`, on every push (any branch), every pull request and `workflow_dispatch`. Python 3.13,
`permissions: contents: read`, no secrets. `concurrency` (`ci-<PR number or ref>`, `cancel-in-progress`) cancels a run
when a newer push to the same branch or PR supersedes it. It replaces `lint.yml` and `e2e.yml`, which ran only on
`main` and on PRs touching certain paths, and had never been seen passing on GitHub. `deploy-web.yml` is unchanged.

| Job | What | Timeout | Run #2 | Link |
| --- | --- | --- | --- | --- |
| `pytest (runtime)` | `services/runtime`, ffmpeg installed so the voice tests run: 1226 passed, 1 skipped | 20 min | 3 min 05 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935205) |
| `pytest (ledger)` | `packages/ledger` | 5 min | 12 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935129) |
| `pytest (connectors)` | `packages/connectors` | 5 min | 12 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935142) |
| `pytest (hmrc-relay)` | `services/hmrc-relay` | 5 min | 13 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935156) |
| `pytest (evals)` | `evals/tests` | 10 min | 21 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935073) |
| `ruff` | `ruff check` + `ruff format --check` (0.17.3) | 5 min | 8 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638934969) |
| `pyright` | 1.1.414 basic over `services/runtime/app`, ledger and connectors (scope in `pyproject.toml`) | 5 min | 16 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935146) |
| `web (eslint, tsc, next build)` | eslint, `next typegen` + `tsc --noEmit`, production `next build`, and a check that `out/` holds no test-mode code | 10 min | 51 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935110) |
| `e2e (Playwright, test mode)` | `e2e:build` + `e2e:test` with `CI=1`, `ACCNOMOS_TEST_MODE=1`: 224 passed, 58 skipped, 0 flaky (5.4 min of tests) | 25 min (test step 18) | 6 min 26 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935149) |
| `flutter (analyze, test)` | Flutter 3.47.8 (Dart 3.13.7, the `pubspec.yaml` floor), `pub get --enforce-lockfile`, analyze, 263 tests | 15 min | 1 min 17 s | [job](https://github.com/zaytunazs/accnomos/actions/runs/40634724575/job/122638935188) |

Caches: uv (keyed on `uv.lock`), pnpm store, Playwright's Chromium headless shell (keyed on the Playwright version;
on a hit only the system libraries are installed), the Next build cache, the Flutter SDK (`subosito/flutter-action`)
and `~/.pub-cache` (keyed on `pubspec.lock`). Run #2 hit the uv, pnpm and Playwright caches.

## Proved locally first

I ran every job's commands in this session before pushing: all five pytest suites; ruff and pyright; eslint, tsc and
`next build`; the full Playwright suite with `CI=1` (224 passed in 8.4 min on this box; it needed a scratch symlink,
because the sandbox's preinstalled Chromium is build 1243 and Playwright 1.64.1 wants 1248, while CI installs its own);
and Flutter 3.47.8 analyze and test. I also ran the Python and Flutter suites again with `TZ=Pacific/Kiritimati
LANG=C LC_ALL=C`, to catch tests that pass only in the author's timezone or locale.

## Fixed along the way (no assertion weakened)

- **Race in `app/sample_books.py`** (`84d049f`). The finished run set the shared in-memory status to "done" *before*
  awaiting the write of `_System/sample_seed.json`. A GET in that window answered "done" while the file still said
  "running", which contradicts the code's own comment ("a page that sees 'done' must find every write finished").
  `test_a_second_press_while_running_or_after_is_the_same_run` failed about one run in five locally. The run now
  saves the finished status first and only then shows it. 8 of 8 repeats passed afterwards.
- **Timezone-dependent Flutter test** (`84d049f`). `drive_item_test` "dates render in UK order" assumed 14:00Z on
  20 Oct is the 20th on the device's clock, which is false at UTC+10 and beyond. It now expects the exact label,
  `'<local day> Oct 2026'`, which is stricter than the old `contains` + `startsWith('20')`.
- **Pages scrolled sideways on narrow phones** (`8488c07`, found by run #1's e2e job). On the runner, `/vehicles`
  was 362 px wide in a 360 px viewport. The quarters table sits in an `overflow-x-auto` wrapper with no positioned
  ancestor, so its absolutely positioned `sr-only` "Action" header escaped the wrapper's clipping and widened the
  whole page whenever the last column passed the edge. The runner's text is a couple of pixels wider than this
  sandbox's, so it showed there first; locally the same page at 300 px measured 346 px before the fix and 300 px
  after it. The three Vehicles wrappers and five others with the same pattern (VAT, Ask answer card, Contacts,
  Autopilot rules) are now `relative`, as `JobDetail.tsx`'s already was.
- **Tests and docs that named the old workflows** (`d501339`, run #1's runtime job). `test_security_routes` read
  `e2e.yml`, and `test_docs` checks that every file the docs cite exists. My first push deleted `e2e.yml` without
  rerunning the runtime suite, which was my mistake. The security test now reads `ci.yml` with the same
  assertions, plus a check that it builds the test-mode export; README, HONESTY and JUDGING cite `ci.yml`.

## Skipped, and why

- `services/runtime/tests/test_seed_demo.py:467` (1 skip): needs `ACCNOMOS_SEED_GRAPH_TOKEN` for a real Microsoft
  Graph account. CI has no secrets by design.
- 58 Playwright skips, all deliberate: `shots.spec.ts` runs only with `SHOTS=1` (submission screenshots); two demo
  steps need HMRC's sandbox and the relay, or the Flutter app, which test mode does not have.
- `pytest-xdist` is not used. The runtime job is the longest Python job at about 3 min, well inside its timeout.
- I watched the runs through the GitHub API and the GitHub MCP tools, not `gh`: `gh` in this session has an invalid
  `GH_TOKEN`.

## Follow-ups (not done here)

- GitHub warns that `actions/checkout@v4`, `setup-node@v4`, `cache@v4`, `upload-artifact@v4`, `setup-uv@v6` and
  `pnpm/action-setup@v4` target Node 20 and are being forced onto Node 24. Nothing fails yet; bump them when their
  Node 24 majors are confirmed.
- The badges in `README.md` track `main`, so they show no status until this branch is merged.
