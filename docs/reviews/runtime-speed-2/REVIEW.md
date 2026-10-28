# Review: runtime round trips, second pass (`claude/runtime-speed-2`)

Three commits on top of `main` (907eeae), one per step. Not pushed.

## What changed

1. **Why the warm dashboard saved nothing** (`evals/harness/bench_runtime.py`). The per-user event cache worked. The
   bench was measuring it cold. The loop clears the process cache before every row, so the `dashboard-revisit`
   row ran straight after `audit day`, which reads no events, and found nothing cached. Checked and ruled out:
   the counting wrapper sits *under* the request memo (Books wraps `CountedStorage`, so a cache hit is never
   counted), and the bench uses one key (`"bench"`) for every request, so the key did not change between them. The
   listings do still cost a trip per month folder (1 + 6 on the seeded book). They are mutable, so they stay
   uncached. The revisit row now gets its own dashboard view first, and each row also records `event_reads`. New test:
   `test_a_second_request_by_the_same_user_reads_no_event_file_twice` (`services/runtime/tests/test_cache.py`).
2. **Fewer and shorter round trips** (`services/runtime/app/`):
   * `cache.py` `RequestMemoStorage`:
     * A **miss is memoised** for the rest of the request (`missing_reads`, `missing_lists`). Any write, move or
       `ensure_folder` clears every remembered miss, and `forget()` clears the misses for that file and its folder.
     * **Concurrent looks at one path share a single round trip** (`_shared`, keyed by kind and path).
     * A read still in flight when the request writes is handed back but **not memoised** (`_epoch`).
     * `Books._update`'s `forget()` is unchanged in effect: the If-Match retry still reads storage, and both
       existing conflict tests pass.
   * `bank_reconcile.reconcile_lines`: every open line looked for `credit_uses.json` again, 17 extra trips on the
     seeded book (the memo did not remember misses). The code suggestions for all open lines now go out together.
     The AI suggestion stays one line at a time, in order, and only when asked.
   * `books.list_event_entries`: a month's event files are read together. They were read one by one.
   * `contacts.load_ledger`: one wave of seven reads instead of two waves.
   * `dashboard.build`: all eight reads go out together instead of in three waves. `unavailable` now lists
     sections in a fixed order (`SECTIONS`). Before, it listed them in whatever order they finished.
   * New tests in `services/runtime/tests/test_route_reads.py` cover each changed route: dashboard, VAT periods,
     the VAT and trend reports, aged, contacts list, contact statements, bank lines, bank reconcile and invoices
     list. On the seeded book, each route must give the same JSON in three runs: bare storage (no memo, no cache),
     a cold memoised request and a warm second request. It must also fetch no path twice in one request and
     re-read no event file when warm. Four new memo tests are in `test_cache.py`.
   * Checked by hand against `main`: I froze one seeded book and ran all 14 bench routes on `main` code and on this
     branch. The JSON is byte-identical, with contacts' made-up-on-the-spot `created_at`/`updated_at` dropped.
3. **Bench re-run** with `--mode after` (`run_before.json` kept). The cache section of `docs/ARCHITECTURE.md` now
   covers memoised misses, shared in-flight reads, the in-flight-write rule and the `_update` forget rule.

## Before / after (fakes, 120 ms per `list`/`read`; round trips / seconds)

| route | before (pre-memo) | main | this branch | trips saved vs main |
|---|---|---|---|---|
| dashboard | 130 / 16.30 s | 130 / 3.12 s | 130 / 2.20 s | 0 |
| review list | 48 / 6.03 s | 48 / 0.87 s | 48 / 0.87 s | 0 |
| VAT return | 3 / 0.37 s | 3 / 0.36 s | 3 / 0.37 s | 0 |
| VAT periods | 68 / 8.55 s | 68 / 2.22 s | 68 / 1.57 s | 0 |
| report P&L | 1 / 0.13 s | 1 / 0.12 s | 1 / 0.13 s | 0 |
| report aged | 129 / 16.27 s | 129 / 3.01 s | 129 / 2.24 s | 0 |
| report VAT | 66 / 8.28 s | 66 / 1.91 s | 66 / 1.25 s | 0 |
| report trend | 66 / 8.30 s | 66 / 1.85 s | 66 / 1.27 s | 0 |
| contacts list | 129 / 16.19 s | 129 / 2.98 s | 129 / 2.26 s | 0 |
| contact statement | 129 / 16.21 s | 129 / 3.33 s | 129 / 2.24 s | 0 |
| bank lines | 245 / 30.76 s | 128 / 3.22 s | 128 / 2.19 s | 0 |
| bank reconcile | 3667 / 463.76 s | 146 / 5.67 s | 129 / 2.71 s | 17 |
| invoices list | 135 / 17.24 s | 128 / 3.22 s | 128 / 2.19 s | 0 |
| audit day | 51 / 8.18 s | 51 / 1.11 s | 51 / 1.11 s | 0 |
| dashboard-revisit (warm) | 130 / 17.35 s | 130 / 3.23 s | 71 / 1.12 s | 59 |

Total across the routes: 633.9 s before the memo, 36.2 s on `main`, 23.7 s here. `evals/runs/bench_runtime/report.md`
has the before/after view the harness writes. **The five slowest routes by trips** were bank reconcile, dashboard,
report aged, contacts list and contact statement. Only reconcile made fewer trips cold. The other four were already
at the floor for this file layout: one file per event and per proposal, every one of them needed, with the mutable
ones re-read on every request by rule. Their gains are in time, from sending independent reads together, and for a
returning user in the warm event cache (59 of the 130 dashboard trips).

The seconds are noisy: the box had a load average of about 13 on 2 cores during the run. The trip counts are exact.

## Not done, and why

* **Listing a folder to stat one file:** `Books._stat` is only used by `exists()`, `_update` (which needs the etag)
  and write paths (`file_document`, `import_bank_csv`, invoice and credit-note numbering, `on_line_changed`,
  `data_export`). None of the timed read routes use it.
* **The dashboard's audit tiles** list `_System/audit` and `_System/audit/autopilot` to find "the last two monthly
  files". Reading two files by month name directly would save 2 trips, but it would give a different answer when a
  month has no file. That breaks the "same numbers" rule.
* **Audit day** reads all 47 proposals to name suppliers. Reading only the proposals that the day's lines mention
  would cut about 45 trips. But `_supplier_names` treats one unreadable proposal as "no names at all", so the output
  would change on a hand-edited book. Audit day is not one of the five slowest anyway. It is a good next step,
  behind a product decision on that rule.
* **Proposals in `load_ledger`** (47 reads) are mutable and needed for VAT numbers and references, so they stay
  per request.

## Risks

* **Memoised misses are a per-request snapshot.** If another device creates a file mid-request, this request goes
  on treating it as missing until it writes something, just as it already treated an existing file as unchanged.
  Any write through the memo forgets every miss, so a request's own creates are always seen.
* **More concurrency.** A full dashboard, or a reconcile with many open lines, now starts many reads at once. The
  per-request gate (`MAX_IN_FLIGHT = 8`) still caps what actually reaches Graph, but more coroutines wait on it.
  When several reads fail together, a different one may now be the first error raised. The tiles and statuses
  stay the same.
* **The cache key is a hash of the access token.** The real app's warm hits last only as long as one Microsoft
  token, about an hour. After a refresh the user starts cold, and the old entries age out of the LRU (1,000 files /
  8 MB). This is deliberate: keying on an unverified claim in the token, such as `oid`, could let a forged token
  read someone else's cached events. I left it as it is.

## Three things a human should check

1. `RequestMemoStorage._shared` and `_epoch` in `services/runtime/app/cache.py`. Is "clear every in-flight entry and
   bump the epoch on any change" conservative enough? Pay particular attention to `write()` failing on a refused
   If-Match or create-only (misses are cleared first, then the path and its listing are forgotten).
2. Run `cd evals && python -m harness.bench_runtime --mode after` on a quiet machine. Do the seconds hold up, and is
   the `dashboard-revisit (warm)` row still 71 trips with `event_reads: 0`?
3. Open the dashboard and the Bank page against a real OneDrive (test account) and watch for Graph 429s. More reads
   now go out together, still at most 8 per request. Also check that `unavailable` and the tile errors still behave
   when a file is hand-edited to bad JSON.

Gates on this branch: `cd services/runtime && python -m pytest -q` passes (1197 passed, 1 skipped);
`ruff check . && ruff format --check .` is clean; `pyright services/runtime/app` reports 0 errors.
`tests/test_ask.py::test_the_timeout_is_per_chunk_not_per_answer` failed once under load and passed on every rerun.
It is a 50 ms timing test that this branch does not touch.
