# Runtime speed on a real-sized book

Book: Bramblewood Joinery Ltd as seeded by `tools/seed_demo.py` (59 ledger events, 2026-10-27).
Storage: in-memory fake OneDrive; every `list`/`read` sleeps 120 ms, standing in for a Graph round trip.
Each row is one request (its own `Books`); the process cache is cleared
between rows, except `dashboard-revisit (warm)`, which is the same user
opening the dashboard again.
**These numbers are on fakes with simulated latency, not on OneDrive**
(`docs/HONESTY.md`). They compare code paths, not the network.
VAT return and report P&L default to the current period, which holds no posted events
in the seeded book (its events are in the two previous periods): those rows show the
cheap default, while VAT periods / VAT summary / trend cover the heavy event reads.

| route | before: trips | before: s | after: trips | after: s | trips saved | time saved |
|---|---|---|---|---|---|---|
| dashboard | 130 | 16.30 | 130 | 3.12 | 0 | 13.18 s |
| review list | 48 | 6.03 | 48 | 0.87 | 0 | 5.16 s |
| VAT return | 3 | 0.37 | 3 | 0.36 | 0 | 0.01 s |
| VAT periods | 68 | 8.55 | 68 | 2.22 | 0 | 6.33 s |
| report P&L | 1 | 0.13 | 1 | 0.12 | 0 | 0.01 s |
| report aged | 129 | 16.27 | 129 | 3.01 | 0 | 13.26 s |
| report VAT | 66 | 8.28 | 66 | 1.91 | 0 | 6.37 s |
| report trend | 66 | 8.30 | 66 | 1.85 | 0 | 6.45 s |
| contacts list | 129 | 16.19 | 129 | 2.98 | 0 | 13.21 s |
| contact statement | 129 | 16.21 | 129 | 3.33 | 0 | 12.88 s |
| bank lines | 245 | 30.76 | 128 | 3.22 | 117 | 27.54 s |
| bank reconcile | 3667 | 463.76 | 146 | 5.67 | 3521 | 458.09 s |
| invoices list | 135 | 17.24 | 128 | 3.22 | 7 | 14.02 s |
| audit day | 51 | 8.18 | 51 | 1.11 | 0 | 7.07 s |
| dashboard-revisit (warm) | 130 | 17.35 | 130 | 3.23 | 0 | 14.12 s |

Total page-load time across these routes: 633.9 s before, 36.2 s after (simulated 120 ms per round trip).
