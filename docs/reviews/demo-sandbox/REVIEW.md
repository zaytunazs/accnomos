# Review: demo sandbox for judges (branch `claude/demo-sandbox`)

Goal: judges, and any visitor, can use the full app on the sample books with no Microsoft sign-in and no two-step
verification, while anyone can still set up their own books by signing in normally.

## Why a sandbox, not a hard-coded sample account

The owner asked to "hard-code the sample account" for judges. Taken literally that means one shared Microsoft account
whose password or refresh token lives on the server, with every judge working in the same OneDrive. I built the same
experience a different way, for four reasons:

1. **No Microsoft credential to store or leak.** A refresh token on the server is a standing credential to a real
   Microsoft account (mail, OneDrive), one log line or misconfigured header away from public. It would also be the only
   user credential the runtime ever kept, breaking "the runtime keeps nothing" (`docs/SECURITY.md`). The sandbox has no
   Microsoft account behind it at all.
2. **Judges don't overwrite each other.** In one shared OneDrive the first judge to approve a receipt or submit a VAT
   return changes it for every judge after them, and two judges at once race. Each sandbox is its own copy.
3. **No two-step verification or sign-in prompts.** A shared account would still hit Microsoft's own security checks
   (new device, unusual location, MFA prompts for a work account) at the worst moment. The sandbox has none.
4. **Nothing can leak into the real world.** A real account can send real email and reach HMRC's sandbox. The demo
   can't: mail is recorded only, HMRC is simulated in the browser, look-ups are off.

What it costs: the sample books live in the runtime's memory (the one place the runtime now keeps state, opt-in and
fictional only), sessions are per process, and a restart ends every demo.

## What was built

Runtime (`services/runtime/app/demo.py`, commit "runtime: per-visitor demo sandbox"):
- `DEMO_MODE=1` (off by default) and `DEMO_SECRET` (32+ characters; the runtime refuses to start in demo mode without
  it). `POST /demo/session` returns a random 24-byte id with an HMAC-SHA256 tag under `DEMO_SECRET`; `GET` says whether it
  is alive; `DELETE` ends it; sending a current id to `POST` drops it first (Reset demo).
- Each session gets a `DemoStorage` copy of a once-a-day snapshot: the whole `tools/seed_demo.py` plan (reused through
  `seed_demo.seed`, plan day = today, every document labelled SAMPLE — FICTIONAL COMPANY), then four inbox documents and
  the two that need a look read into Review with the seed's gold reading. The bytes are immutable and shared; a copy
  costs ~7 µs.
- `X-Demo-Session` replaces `X-Graph-Token`: `get_books`, `get_mail`, `get_address_book`, `get_calendar`, `get_sender`,
  the actions' `graph_token` (so actions are signed per session) and their mail sender all map to the session's
  in-memory fakes. The demo header wins over a Graph token sent with it, and a forged/expired/switched-off one is a 401,
  never a fall-through. `/lookup/*` answers 403 in a demo. The browser's Graph calls go to `/demo/graph/v1.0`, a Graph
  look-alike now shared with test mode (`app/fake_graph.py`, moved out of `testmode.py` unchanged in behaviour).
- Limits: 200 sessions with LRU eviction, 2 h idle TTL, 20 MB / 300 new files per session, 10 MB per file (413),
  512 MB added across sessions (LRU out), 5 session starts a minute per IP, 600 Graph look-alike calls a minute per
  session (those are exempt from the per-IP budget, which one Files page would exhaust). `X-Demo-Session` is a credential
  header (8 KB cap, HTTPS-only behind a proxy, scrubbed from logs). `/demo/graph/` takes uploads up to 11 MB (security
  middleware and `deploy/nginx.conf`).
- AI: untouched. A demo uses `ai_config_from_request` like everyone else, so whatever provider chain is configured
  (including `AI_PROVIDERS` when it lands) serves it.
- Test mode and its image guard (`ACCNOMOS_IMAGE=1` refuses `ACCNOMOS_TEST_MODE=1`) are untouched; demo mode is allowed
  in the image and never turns test mode on (tested).

Web (commit "web: Try the demo…"):
- `src/lib/demo.ts`: the session id lives under an `msal.` localStorage key, so the app treats the device as signed in
  (and Settings › Disconnect clears it like a sign-in); `getMsal()` hands out a fake whose one account is the demo
  visitor. `runtimeHeaders()` sends `X-Demo-Session`; `graph.ts` talks to `/demo/graph`. No page needed its own demo
  branch for data.
- *Try the demo — no sign-in* on the signed-out landing (Pitch) and on Connect, shown only when `/health` reports the
  demo on. A banner on every page in a demo: "SAMPLE — FICTIONAL COMPANY · Demo sandbox with sample data — changes reset
  after 2 hours. Set up your own books → · Reset demo"; Reset demo and Leave demo in the sidebar menu; an ended session
  says so and offers a new one. Leaving goes to `/connect` and the real sign-in; Connect inside a demo explains instead
  of offering "Create my folder".
- `/judges` (also in the footer): what the sandbox is, the seven things to try in order (Review a receipt, Approve, VAT
  return, Ask, Reports, Contacts, Bank), what is real and simulated, and that signing in with Microsoft sets up real
  books in the judge's own OneDrive. One button starts a demo and opens Review.
- HMRC in a demo: `lib/hmrc.ts` never calls the relay (it throws if anything tries); connecting, obligations and the
  receipt are simulated and labelled "Demo — submission simulated" (badge "Demo · HMRC simulated"). Sends read "Sent (demo
  — not actually sent)". Look-ups and the setup checklist are hidden in a demo.

Android: not done; noted in `docs/HONESTY.md`. The phone calls Graph itself for capture, Review and Files, so it needs
those calls re-pointed as well as a button; the runtime API is ready for it.

Docs: `docs/SECURITY.md` (threat model exception, protection row, per-process and AI-cost notes), `docs/PRODUCTION.md`
(section 5: every `DEMO_*` variable, behaviour, and "the demo stays a sandbox" under what must not change),
`docs/HONESTY.md` ("Demo sandbox"), `docs/submission/JUDGING.md` (the judges' path), `.env.example` and
`deploy/docker-compose.yml` (`DEMO_MODE`, `DEMO_SECRET`).

## Seed time (measured)

On this machine (2 cores, shared with other agents' builds, load average 32–38): the seed alone 68 s; the full snapshot
(seed plus six pre-read documents) 125 s; a per-session copy ~0.007 ms. The brief's "~4 s" could not be checked on an
idle machine. Hence the snapshot: built once per day in a background thread started by the first `/health` request, so it never slows start-up (waiters poll, they don't hold
worker threads), re-built on the first session of a new day, deep-copied per session at dict level.

## Tests and gates

- `services/runtime/tests/test_demo.py` (28 tests): off by default; refused without / with a short `DEMO_SECRET`; a demo
  header never falls back to Graph when demo mode is off; the image guard; sessions are signed; forged, unknown and
  other-secret tokens refused; two sessions never see each other's writes (Graph look-alike and `get_books`), a later
  session starts clean, the snapshot is built once; Reset and Leave; idle TTL; LRU eviction; the total-bytes cap;
  per-file / per-session bytes / file-count limits and the 413; per-IP session-start limit; per-session Graph limit; a
  failed seed is a 503 and retried; waiters share one build; no Graph storage, mail, contacts, calendar or sender client
  is built in a demo (each constructor replaced by one that fails), the sender only records, the action key is
  per-session; look-ups refused; the header is scrubbed.
- `apps/web/e2e/sandbox.spec.ts`: Try the demo from the landing (real seed), review and approve a receipt, the VAT
  return and a simulated submission with zero relay calls, Reset demo (approval gone), leave to sign-in; `/judges` starts
  a demo in one click. The e2e runtime runs with `DEMO_MODE=1` (`playwright.config.ts`).
- Gate results: see the end of this file.

## What remains / risks

- **Never run on the production server**, and not on an idle machine; seed time there is unmeasured.
- **Sessions are per process and in memory.** One runtime process (as the image runs) or sticky routing on
  `X-Demo-Session`. A restart or deploy ends every demo (the banner says so).
- **The demo spends the server's AI** (scans of the 19 inbox documents, Ask, planner). Bounded only by the rate limits.
- **Pre-read documents** are labelled `seed:gold-reading`, like every seeded document; the judges' page says they were
  pre-read.
- The demo's mailbox, address book and calendar are small fictional stand-ins, not the seed's.
- The simulated HMRC obligations are calendar quarters (the sample books' stagger 1).
- Android: no demo yet.
