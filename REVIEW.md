# Review: public website, navigation and "Ask about Accnomos" (branch `claude/marketing`)

## What changed

**Public website (signed out).** `/` is now a landing page; the old signed-out Home (Pitch plus the Bramblewood sample
dashboard) moved to **`/try`** ("Try the sample books"). Signed in, `/` is Home exactly as before.

- `apps/web/src/components/SiteShell.tsx` is the one switch: signed-out visitors on `/`, `/how-it-works` and
  `/privacy` (`lib/public-site.ts`) get `components/marketing/MarketingShell.tsx` (public top menu, footer, chat);
  everything else, and every route once the device is signed in, gets the unchanged `AppShell.tsx`. The parallel
  `claude/profiles` header belongs in `AppShell`; nothing public is shared with it. `layout.tsx` changed one line
  (plus a tiny pre-paint script so a signed-in owner never sees the landing page flash).
- Top menu (`PublicHeader.tsx`): Features, How it works, Security & privacy, FAQ, Ask about Accnomos, Sign in, Try the
  sample books. Below 1024 px a Menu button (aria-expanded/controls, Escape returns focus) opens the same list.
- Landing (`Landing.tsx`, server component): hero "AI proposes. You approve. Code calculates." with phone and web
  frames of the same Novex receipt; the **process animation** (`ProcessDemo.tsx`): snap on phone → model reads →
  code checks → approve on phone or web → Box 4 fills, five real screens crossfading with a brass spotlight on the part
  that matters; plays only while on screen, never with `prefers-reduced-motion`, Pause/Play, step buttons. Then
  Android ("Made for the phone in your pocket"), features with a tabbed screen viewer, Ask and actions, your data in
  OneDrive, the six Meta models table with each status, "What is tested, and what is not", FAQ, closing CTA.
- Screens: `apps/web/public/shots/*.webp` (17 files, 15–49 kB each), crops/resizes of `docs/submission/shots/` and
  `apps/mobile/screenshots/` made by `apps/web/scripts/marketing-images.py`. Nothing drawn or edited; captions say
  "test mode, fictional sample books" (some crops show `accnomos-test-stub`). Hero images eager, all others lazy.
- In the app shell, signed out, the sidebar's Home links to `/try` (`AppNav.tsx`), so the sample stays one click away.
- Privacy page: a data-map row for questions typed into the website chat.

**Owner additions (mid-task).**
- Phone first (hero copy, step 1 "Snap it on your phone", Android section moved up), Outlook email intake as a
  feature and FAQ.
- `NEXT_PUBLIC_SUBMISSION_MODE` (default `1`, inlined in `next.config.ts`; set in `deploy-web.yml` from the repo
  variable `SUBMISSION_MODE`). `1`: "Try the demo" + "Sign in with Microsoft", "Available on Android", no launch date,
  nothing "coming soon". `0`: "Launching November 2026 — get notified" (`mailto:` the contact address, subject "Notify
  me at launch"), "Try the demo" second, sign-in as a quiet "Early access / testers" menu link, iPhone app and more
  mailboxes as coming soon, launch FAQ. The chat's notes follow `PUBLIC_SUBMISSION_MODE` (`[prelaunch]` /
  `[submission]` lines in `public_kb.md`).
- "Try the demo" links to `/judges` if `src/app/judges/page.tsx` exists at build time, else `/try`.

**Runtime chat** `POST /public/chat` (`services/runtime/app/public_chat.py`, KB `app/public_kb.md`, 16 sections):
keyword/title retrieval in code (top 3); role-change regex and no-match questions get a fixed reply naming
`PUBLIC_CONTACT_EMAIL` without a model call; strict JSON `{answerable, answer, sections}` from the server's own model
(`PUBLIC_CHAT_AI_MODE`, default local Glimmer; visitors' `X-AI-*` ignored); citations limited to retrieved sections;
foreign links/e-mails stripped; 700-character cap at a sentence; 500-character question cap; own per-IP limit
(`PUBLIC_CHAT_PER_MIN`, default 6); two concurrent model calls, 60 s timeout, then the best note quoted as written;
nothing about the question logged. Test-mode stub answers with the first note's first sentence.
Web widget `ChatWidget.tsx` (lazy-loaded): modal dialog, focus trap, Escape and focus return, `aria-live` log,
starter questions, 360 px full screen, "AI answers about Accnomos only … contact the team at …".

**Docs.** `docs/HONESTY.md` (new section: chat untested on the live Spark, keyword retrieval limits, the two builds,
"Available on Android" caveat), `docs/PRODUCTION.md` §3a (all env vars), `.env.example`, `deploy/docker-compose.yml`.

## Screenshots (taken with `node apps/web/e2e/marketing-shots.mjs`, test-mode export)

`docs/reviews/marketing/shots/`: `landing-top-{1280,360}.png`, `landing-full-{1280,360}.png`, `menu-open-360.png`,
`chat-{1280,360}.png`, `privacy-{1280,360}.png`, `how-it-works-{1280,360}.png`, `try-{1280,360}.png`.
They predate the owner's last two rounds of copy changes (phone-first hero, submission-mode CTAs); re-run the script
for current ones.

## Tests

- Runtime: `tests/test_public_chat.py` 49 passed (KB parsing and honesty lines, retrieval, off-topic and 8 injection
  phrasings refused without a model call, citations restricted, not-answerable and leaking replies refused, link and
  address stripping, length caps, fallback on model trouble, 422 on long/unknown bodies, visitor AI headers ignored,
  local-by-default, rate limit with Retry-After, switch-off, nothing logged, stub, both submission modes);
  `test_security_routes.py` updated (route listed as needing no X-User; module in the HTTP allow-list).
  RESULT_PYTEST
- `ruff check .` and `ruff format --check .`: clean. `pyright services/runtime/app`: RESULT_PYRIGHT
- Web: `pnpm exec eslint .` clean. RESULT_BUILD
- e2e (`CI=1`, ports 3160/8796/8804 as instructed): RESULT_E2E
  New: `e2e/marketing.spec.ts` (hero and one-click demo, menu, FAQ, lazy images, process animation with clock control
  and reduced motion, 360 px no sideways scroll, mobile menu, chat answers/refusals/focus trap/rate-limit message,
  signed-in routes are the app) and `e2e/submission-mode.spec.ts` (no "coming soon", "beta", "launching", "early
  access" anywhere in the export). Updated: `pages.ts` (+`/try`), `signed-out.spec.ts` (public routes have no SAMPLE
  banner and "Sign in…" CTAs), `home.spec.ts`, `phone.spec.ts`, `shots.spec.ts`, `site-health.spec.ts` (signed-out
  sample Home checks moved to `/try`; none deleted). `playwright.config.ts`: `PUBLIC_CHAT_PER_MIN=0` for the test
  runtime, runtime start-up timeout 60 → 240 s (test-mode warm-up took ~100 s on this loaded machine).

## Risks and what a human should check

1. **The chat has never run against Glimmer on the Spark.** Ask it 10–20 real questions in production (or locally with
   `OLLAMA_BASE` pointed at the Spark) and read the answers; check latency and that the JSON schema is honoured.
2. **Retrieval is keywords.** A sensible question in unexpected words is refused with the contact address; widen
   `Keywords:` lines in `public_kb.md` from what visitors actually ask.
3. **Claims to confirm:** "Available on Android" (Play listing was "in review" on 27 Oct per JUDGING.md, no real-phone
   sign-in recorded); the FAQ says HMRC submission is tested against a stand-in and not run end to end against the
   sandbox, which is what `docs/HONESTY.md` says; I did not use "sandbox-tested". The "Not in this build" column stays in
   the submission build because it is the honest scope statement judges look for; delete it if the owner disagrees.
4. **Pre-launch build (`0`) is type-checked only**; build it once and look before switching after judging. The e2e
   signed-out sweep expects a "Sign in" link on public pages, which the `0` build moves into the menu.
5. **`/judges`**: when the parallel branch lands, add `/judges` to `e2e/pages.ts`, or the signed-out link check will
   fail on the landing page's demo link.
6. Merge points with other branches: `layout.tsx` (one line), `AppNav.tsx` (Home → `/try` signed out),
   `DemoBanner.tsx`, `Pitch.tsx` (`next=/try`), `playwright.config.ts`, `test_security_routes.py`, `testmode.py`.
7. Signed-in owners opening `/` see the landing page until `localStorage` is read (hidden by the pre-paint probe; a
   blank frame at worst). Performance: the landing adds ~400 kB of lazy WebP, hero ~70 kB; route JS sizes RESULT_SIZE.
