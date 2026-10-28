# Review: site layout — a marketing home for visitors (branch `claude/site-layout`)

The owner's ask: accnomos.com/ must be a proper marketing page for visitors, not the app. Today `/` looks as if
someone is signed in and working.

Branch: `claude/site-layout` from `origin/main` (3c2f1d2), with `origin/claude/known-fixes` merged in at the start
and again at the end. known-fixes carries `claude/marketing`, `claude/exports`, `claude/sales-purchases` and
`claude/accounting-tools`. Pushed to `claude/site-layout` only: no PR, nothing to `main`.

## 1. How the live site was reviewed

- **accnomos.com was blocked from this session** (the environment's network policy answered 403 to the tunnel), and so
  was www.gov.uk. Instead the **`origin/site` branch** was served locally. That branch is the exact static export the
  deploy workflow publishes and Plesk serves at accnomos.com (`e361e54`, "site: 8c2e945…", 28 Oct 14:08). Unknown
  paths fell back to `404.html`, as on Plesk.
- Playwright (Chromium) took full-page screenshots at **1440 px and 390 px** of `/`, `/try`, `/how-it-works`,
  `/judges`, `/privacy`, `/connect`, `/review`, `/vat` and `/settings`, signed out. For each page it also recorded the
  h1, the navigation landmarks, the sideways overflow and any pre-launch words.
- No runtime was reachable from that static copy, so the "before" shots also show the amber "The reader at
  api.accnomos.com isn't answering" strip. The live site would not show it. Everything else is the live markup.
- The code was read alongside: `layout.tsx`, `AppShell.tsx`, `TopBar.tsx`, `AppNav.tsx`, `app/page.tsx` and the
  `claude/marketing` components brought in by known-fixes.

## 2. What was wrong (before: `docs/reviews/site-layout/before/`)

| # | Problem | Where |
|---|---------|-------|
| 1 | **Signed out, `/` is the app, not a website.** The h1 is "Good evening, Priya". You see cash in bank £12,480, "Needs attention 3", To-dos, Inbox, Deadlines, Month-end, Plan today, Spending and "What the agents did on 26 October". A visitor reads it as someone's live books. | `before/home-1440.webp`, `home-390.webp` |
| 2 | **In-app chrome with nobody signed in.** The full app sidebar (Books, Money, Buying, Work, Settings), a **"Review 1"** badge, the "Your books live in OneDrive" box and "AI: the server's Meta models". At 390 px there is the app's tab bar (Home, Review, Ask, VAT, Files) and a Settings link. | every before shot |
| 3 | **No public navigation.** There is no Features, How it works, Pricing or Sign in in the top bar. The only "menu" is the app's. The footer is the app's ("How it works · Privacy · For judges · Meta models at work · Settings"), with no terms, no contact and no honesty link. | `before/home-1440.webp` (bottom) |
| 4 | **The promise is buried.** The pitch card ("Books read by AI…") shares the page with a dozen sample tiles. "Connect your OneDrive" appears three times, and there is no "Try the demo" or "Sign in with Microsoft" pair. | `before/home-*.webp` |
| 5 | **Dead ends.** `/try` is a **404** on the live site; it is the sample Home that the marketing branch links to. Signed out, To-dos, Month-end, Plan today and Spending each say "Sign in to …", which is four tiles of nothing for a visitor. | `before/try-1440.webp`, `home-1440.webp` |
| 6 | **`/judges` (the demo entry) is inside the app shell**, with the sidebar, review badge and the SAMPLE strip. | `before/judges-1440.webp` |
| 7 | No sideways scroll at 1440 or 390, and no pre-launch words on any page swept: these were fine. | the sweep's output |

## 3. What changed

### Routing (no app URL moved)

| Who | `/` | `/how-it-works`, `/privacy`, `/terms`, `/judges` | Every other route |
|-----|-----|-----------------------------------------------|-------------------|
| Signed out | **Marketing home** (public shell) | Public shell | App shell with the labelled sample (unchanged) |
| Signed in (Microsoft, or inside a demo sandbox) | **Dashboard**, in the app shell | App shell | App shell |

- **The app stays where it is.** Moving it under `/app` would have meant redirects in a static export on Plesk, and
  every existing deep link (docs, Android, the judges' guide, e-mails) would have had to keep working. Keeping the
  routes and switching only the shell meets the same goal with nothing to redirect.
- `SiteShell.tsx` is the one switch (from `claude/marketing`). `lib/public-site.ts` `PUBLIC_PATHS` now adds `/terms`
  and `/judges`.
- The pre-paint probe in `layout.tsx` hides the public shell on a signed-in device until React swaps in the
  dashboard, so there is no flash.
- A demo session is stored under an `msal.` key, so it counts as signed in. Inside a demo, `/judges` keeps the app
  shell and the demo bar.

### Public top bar (`components/marketing/PublicHeader.tsx`)

- Items: **Features · How it works · Accountants · Pricing & FAQ · Ask about Accnomos · Sign in · Try the demo**.
- All items are in the bar from 1280 px. Below that, a Menu button (aria-expanded and aria-controls; Escape returns
  focus) opens the same list.
- It has nothing from the app: no profile switcher, review count, to-dos or greeting. The signed-in menu bar from
  `claude/profiles` (`TopBar.tsx` in `AppShell`) is untouched and never shares code with it.
- "Security & privacy" and "Try the sample books" moved to the footer.

### Footer (`MarketingShell.tsx`)

- **Product:** Features, How it works, For accountants, Pricing, Try the demo, Browse the sample books.
- **Trust:** Privacy policy, **Terms of use** (new `/terms`), What is tested, **What is not tested (HONESTY.md)**, which
  links to the public repository's `docs/HONESTY.md`.
- **Help:** FAQ, How each feature works, **Contact us** (`mailto:` the contact address, from
  `NEXT_PUBLIC_CONTACT_EMAIL`, the web twin of the runtime's `PUBLIC_CONTACT_EMAIL`; the default is the address the
  chat names).

### The home page (`components/marketing/Landing.tsx`), top to bottom

1. **Hero.**
   - Audience line: "Bookkeeping and Making Tax Digital for UK small businesses, sole traders, landlords and personal
     finances".
   - The one promise: "AI proposes. You approve. Code calculates." Supporting line: forward a receipt, snap a photo or
     say what you need; Accnomos proposes, you approve, VAT and Income Tax figures ready for HMRC, books in your
     OneDrive.
   - Calls to action: **Try the demo** and **Sign in with Microsoft**.
   - Real app screens: the laptop and phone frames.
2. **One set of books, whoever you are.** Small businesses, sole traders, landlords and personal finances, each with
   only what this build does. Landlords: "Separate property-income (SA105) figures are not in this build."
3. **How it works.** Four steps (send it in by email, photo, upload or voice → AI proposes → you approve →
   HMRC-ready), then the existing five-screen process animation.
4. Features, with the tabbed real screens (unchanged from marketing).
5. **Making Tax Digital, for VAT and Income Tax** (new). Two cards, each stating its status: VAT sandbox, tested
   against a stand-in; Income Tax sandbox only, never run against HMRC. A real VAT-return screen.
6. **Ask by voice or chat** (retitled), with the action card.
7. Android ("Made for the phone in your pocket"). The iPhone chip shows only when submission mode is off.
8. **For accountants** (new): Books.xlsx, CSV exports, the audit trail, and sharing the folder in OneDrive. "A portal
   for accountants is not in this build."
9. Your data, the six Meta models, and what is tested. That last section now links to HONESTY.md.
10. **Pricing** (new). Submission build: "No charge. There is no published pricing: Accnomos is a hackathon build…".
    Pre-launch build only: "Free while we launch".
11. FAQ, closing calls to action, and the product-only chat widget (unchanged from marketing).

### "Try the demo" (`components/marketing/DemoLink.tsx`)

- One click starts a demo sandbox (`lib/demo.ts` `startDemo`, no sign-in) and opens the judges' guide **inside** it,
  with the demo bar.
- Underneath it is a plain `<a href="/judges">`. Without scripts, on a modified click, or when the server runs no
  demos, it lands on the guide, which explains and keeps its own Start button.
- The hero's separate "Try the demo — no sign-in" button was removed, so there is one demo call to action.

### Submission mode

- Nothing new says coming soon, beta, early access, launching or testers.
- "Free while we launch" is the only new pre-launch phrase. It renders only when `NEXT_PUBLIC_SUBMISSION_MODE=0`, in
  a server component, so it is in neither the HTML nor the JS of the default build.
- "iPhone app: coming soon" still shows only when submission mode is off.
- The production export (`pnpm build`) was scanned: `node scripts/prelaunch-words.mjs out` checked 270 files and
  found 0 phrases.

### Performance and accessibility

- **LCP:** only the hero laptop screen has `fetchpriority="high"` (a new `priority` prop on `Shot`). Its entrance
  animation now only slides (`hero-slide`) instead of fading in from opacity 0, which used to hold back the LCP
  paint.
- **Responsive images:** a 200 px phone-frame image (`hero-phone-200.webp`, 9 kB, made by
  `scripts/marketing-images.py` from the same screenshot) with `srcset`; the laptop screen's `sizes` is now 72vw.
- **Reduced motion:** the global rule in `globals.css` still neutralises every animation, and the process animation
  never advances by itself (covered by `marketing.spec.ts`).
- **No sideways scroll at 360 px** on all five public pages (`marketing.spec.ts`).
- `/judges` copy no longer says "the sample label shown at the top of this page", since the public shell has no
  SAMPLE strip.

### The known-fixes merge (21 conflicts, resolved by keeping both sides)

- Menus: main's Month-end, Self-employment and Buying (Spending, Cheaper options, Shopping list) sit next to marketing's
  `/try`.
- Home: the known-fixes `HomeDashboard` gains main's Month-end and Spending cards.
- Chat and AI: the public chat's stub and routes sit beside main's AI-provider ones.
- Android: More keeps known-fixes' profile gating and adds main's Month-end and Personal entries;
  `more_gating_test.dart` expects Month-end.
- Imports: `TopBar` imported `usePersonalOn` twice, which broke the build; fixed.
- Removed `docs/reviews/profiles/HANDOVER.md`, which known-fixes had deleted.

## 4. Tests

| Gate | Result |
|------|--------|
| `cd services/runtime && python -m pytest -q` | **1711 passed, 2 skipped** (306 s) |
| `ruff check .` / `ruff format --check .` | clean (448 files; one merge-formatting fix in `testmode.py`) |
| `pyright services/runtime/app` | 0 errors, 0 warnings |
| `pnpm install --frozen-lockfile`, `pnpm exec eslint .`, `tsc --noEmit` | clean |
| `pnpm run e2e:build` + `pnpm run e2e:test` (`CI=1`, 3 workers) | **379 passed, 0 failed, 0 flaky, 94 skipped** (14.6 min; the skips are `shots.spec.ts` and `design-shots.spec.ts`, which run only with `SHOTS=1`) |
| `pnpm build` (production) + `prelaunch-words.mjs out` | built; 270 files, 0 pre-launch phrases |
| Flutter | `flutter` is not installed in this container: `more_screen.dart` (merge) and `more_gating_test.dart` were not run here |

New in **`e2e/site-layout.spec.ts`** (6 tests):

- Signed out, `/` shows every section heading and the four steps, with both calls to action in the hero. It has no
  app chrome: no Main or Sections navigation, profile switcher, "to review", To-dos, greeting or SAMPLE strip. The
  footer has privacy, terms, a `mailto:` contact and HONESTY.md.
- The LCP image is eager with high fetch priority, it is the only high-priority image, and its opacity is 1 from the
  start.
- `/terms` and `/judges` are in the public shell signed out.
- Signed in, `/` is the dashboard: "Good …, Sam", the menu bar, no public bar, no marketing sections.
- **Every app URL still works:** each of the 38 routes in `e2e/pages.ts` answers 200 with no "Page not found", signed
  out (public shell exactly on the five public routes) and signed in (always the app shell with the menu bar).

Updated:

- `marketing.spec.ts`: the new menu items, the footer links, and no-sideways-scroll checks for `/terms` and `/judges`.
- `sandbox.spec.ts`: the landing page's "Try the demo" link now starts the sandbox and lands on `/judges` with the
  demo bar, then runs the existing review → approve → VAT (simulated) → reset → leave path. **This is the "demo CTA
  opens the sandbox" e2e.**
- `signed-out.spec.ts`: `/terms` and `/judges` are public, so they have no SAMPLE strip and their CTA is "Sign in".
- `pages.ts`: adds `/terms`, which puts it in the axe, phone, signed-out and submission-mode sweeps.

**Lighthouse 12.8.2**, local, `/`:

| Build | Performance | Accessibility | Best practices | SEO | LCP | CLS | TBT |
|-------|-------------|---------------|----------------|-----|-----|-----|-----|
| Production export, gzip, mobile | 96 | **100** | 96 | 100 | 2.6 s | 0 | 130 ms |
| Production export, gzip, desktop | 100 | **100** | 96 | 100 | 0.7 s | 0 | 0 ms |

- Best practices loses 4 points for one console 404: `/version.json`, which only the deploy workflow writes.
- The uncompressed test-mode export scored 78 on mobile. Its *observed* LCP was 239 ms; the simulated figure
  (5.5 s) comes from 1.2 MB of uncompressed test-mode JavaScript.
- axe: `e2e/a11y.spec.ts` sweeps every page in `pages.ts`, now including `/terms`, with no violations (part of the 379 passing tests).

## 5. Screenshots

- **Before** (the live site's export, signed out): `docs/reviews/site-layout/before/`
  - `home-{1440,390}.webp`, `try-{1440,390}.webp` (the live 404), `how-it-works-*`, `judges-*`, `privacy-*`,
    `connect-*`, `review-*`, `vat-*`, `settings-*`
- **After** (this branch, final test-mode export): `docs/reviews/site-layout/after/`
  - `home-top-{1440,390}.webp` (first screen), `home-{1440,390}.webp` (whole page), `menu-390.webp` (phone menu open)
  - `signed-in-home-{1440,390}.webp`: signed in, `/` is the dashboard with the profiles menu bar
  - `judges-{1440,390}.webp`, `terms-{1440,390}.webp`, `privacy-*`, `how-it-works-*`
- All screenshots are WebP at quality 70; full pages longer than 16,000 px are cut at that height.
- To retake them, serve the export and run a full-page Playwright capture at 1440 × 900 and 390 × 844, scrolling once
  so lazy images load. The script used was a scratch file, not committed.

## 6. Risks and what a human should check

1. **Terms of use are not lawyer-reviewed.** They were written from README, HONESTY and the privacy policy, and say
   so in a code comment. Have them checked before real customers rely on the service.
2. **No MTD rule dates or thresholds on the page.** gov.uk was unreachable from this session, so the page states only
   what the app does. If the owner wants "MTD for Income Tax from April 2026 for income over £…", verify it on gov.uk
   first and cite the URL and date.
3. **Landlords and accountants are described by what worked on this branch's base**: the same books; a shared
   folder, Books.xlsx, exports and the audit trail. **`origin/main` has since merged `claude/accountant`**
   (`90cddb55`: accountant portal, Settings › Your accountant, client queries). When this branch is merged with
   main, replace "A portal for accountants is not in this build" in `Landing.tsx` `Accountants()` with the portal,
   and point the card at `/accountant`. Do the same for landlords when `claude/landlords` merges, and update
   `public_kb.md`, which the chat answers from.
4. **"Try the demo" waits for the sandbox** (the first visitor of the day can wait while the seed runs), showing
   "Preparing the sample books…". If it fails it still goes to `/judges`, which shows the reason.
5. Check the live site after deploy: Plesk compression, the `version.json` 404, and a real Lighthouse run on
   accnomos.com.
6. Not run: Flutter tests, and the pre-launch build (`NEXT_PUBLIC_SUBMISSION_MODE=0`) in a browser.
