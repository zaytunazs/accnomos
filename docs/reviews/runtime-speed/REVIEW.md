# Review: muse/runtime-speed (27 Oct 2026)

Per-request memo of OneDrive reads, a per-user cache of immutable ledger event files, and parallel reads (`app/cache.py`, `app/books.py`).

| Check | Result |
|---|---|
| Users never share cache entries | Yes: key is a SHA-256 of tenant + token; tokens are not kept |
| Only immutable files cached across requests | Yes: `_System/Ledger/events/*.json`, written once with unique names (`{ts}-{device}-{id}`) |
| Read-modify-write (`Books._update`) | **Fixed in review.** The memo served the stale listing and bytes to the If-Match retry: a write from another device between this request's read and its write was overwritten (fresh etag + stale bytes), and the create-only loser in the actions log raised instead of reading the winner's claim. `_update` now calls `RequestMemoStorage.forget(path)` before stat and read; a refused conditional write also forgets. Two tests added (both failed before the fix). |
| Graph throttling from `asyncio.gather` | Capped at 8 round trips in flight per request (semaphore in the memo); the Graph client already retries 429/503 with Retry-After |
| Bench numbers | On fakes with simulated latency only (HONESTY.md says so) |
| Bench (re-run after the fix, 27 Oct) | Total across the main routes 633.9 s → 36.2 s at a simulated 120 ms per round trip; bank reconcile 3,667 → 146 trips. Most of the gain is parallel reads, not fewer trips. The warm dashboard revisit saves no trips: the per-user event cache is keyed by token hash and the bench shows it not helping yet — runtime-speed-2 is asked to look. `evals/runs/bench_runtime/report.md` |
