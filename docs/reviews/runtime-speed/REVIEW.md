# Review: muse/runtime-speed (27 Oct 2026)

Per-request memo of OneDrive reads, a per-user cache of immutable ledger event files, and parallel reads (`app/cache.py`, `app/books.py`).

| Check | Result |
|---|---|
| Users never share cache entries | Yes: key is a SHA-256 of tenant + token; tokens are not kept |
| Only immutable files cached across requests | Yes: `_System/Ledger/events/*.json`, written once with unique names (`{ts}-{device}-{id}`) |
| Read-modify-write (`Books._update`) | **Fixed in review.** The memo served the stale listing and bytes to the If-Match retry: a write from another device between this request's read and its write was overwritten (fresh etag + stale bytes), and the create-only loser in the actions log raised instead of reading the winner's claim. `_update` now calls `RequestMemoStorage.forget(path)` before stat and read; a refused conditional write also forgets. Two tests added (both failed before the fix). |
| Graph throttling from `asyncio.gather` | Capped at 8 round trips in flight per request (semaphore in the memo); the Graph client already retries 429/503 with Retry-After |
| Bench numbers | On fakes with simulated latency only (HONESTY.md says so) |
