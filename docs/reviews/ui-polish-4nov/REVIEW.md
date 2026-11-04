# UI polish, 4 Nov 2026 (branch `claude/ui-polish`, from `integ/4nov-big` 8debc2e9)

A presentation-only pass on the outside UI review's items 1–7. No data loading, arithmetic, routes, handlers,
APIs, AI calls or permissions changed; every control is still there and reachable; no wording was dropped. The
brand stays: #5A2D00 primary, cream #F8F6F3, gold #C9A45C, the 232 px sidebar, white cards.

## What changed, per item

1. **Home hierarchy** (`components/home/HomeDashboard.tsx`, `Snapshot.tsx`). Business Home now reads: the sample
   banner / "load the sample books" offer and any load error → Your summary → the ask bar → What needs attention →
   **Business snapshot** (the compact year-to-date strip) → **Goals & progress** with its note → **Trend and cash**
   (the last 12 months and the 90-day cash line) → setup checklist, earlier-files notice, then the card grid (Today,
   Money, Coming up, …) and activity. `BusinessSnapshot` is split into `SnapshotYear` and `SnapshotCharts`; both read
   the one `GET /books/home` already fetched by `OverviewData` (recomposed, not recomputed). The strip's figures are
   22–24 px with tighter padding; its period line and links share one row. The household Home follows the same
   order: error → summary → ask bar → what needs attention → This month → Goals → Budgets and Bills → Where the money
   went → the rest. Also: the monthly chart's left gutter is sized to its widest axis label, so seven-figure books
   no longer clip "£1,000,000" (seen in the large-values check).
2. **Goals** (`home/HomeGoals.tsx`, `goals/GoalCard.tsx`, `goals/LiveGoals.tsx`). The note ("What your goals are
   telling you") is rendered once, first in the DOM, with `md:order-last` in the section's flex column: under the
   heading on a phone, after the cards from 768 px — DOM order is the reading order at both. Card weight: name and
   status badge → the current figure at 30 px → target line and progress bar → one variance sentence → the quieter
   inset (needed / run-rate estimate, now muted with the figure in bold) → source line at 12 px → View details.
3. **Navigation** (`components/TopBar.tsx`). Only the current page's own item keeps the filled selected style. A
   group that holds the current page is bold with a brass left bar in the sidebar (≥ 1280 px) or an underline in
   the 900–1279 px bar — not the same filled background. On `/vat` both Reporting and Tax carry the quiet mark and
   "VAT returns" inside each is the filled item; on `/contacts/customers` Sales and More do the same; on `/review`
   the Review link is filled and Purchases (Bills) carries the mark. Plain links (Home, Review, Bank) keep the fill.
   `lib/nav.ts` untouched: routes and structure are as before. Under 400 px the bar's Ask icon hides — the phone
   tab bar's Ask tab is the way there — so the profile line has room (item 7).
4. **Brand finish** (`goals/*`). `#BFDDD6` → `border-border`, `#E3EBEF` → `bg-border`, `#F3F6F8` → `bg-ground`;
   the goal hex colours for green/amber/red become the `pos-*`, `warn-*`, `neg-*` tokens; `accent-[#5A2D00]` →
   `accent-teal`. Corners: goal cards, the note, the add-goal section and the details panel are 12 px
   (`rounded-2xl` = 0.75 rem in `globals.css`); goal controls, insets and the note's icon box are 8 px (`rounded-xl`).
   No `teal-*` utility was renamed.
5. **Status badges** (`components/StatusBadge.tsx`, new). One treatment — `rounded-full px-2 py-0.5 text-[12px]
   font-bold leading-4` — with tones: success (pale green: Paid, Matched, Exact, Refund of a credit, done, On
   track), neutral (quiet grey with an inset ring: Draft, Void, Unmatched, Transfer, Ignored, Bank rule, counts,
   Confidence), warning (amber: overdue, At risk, Suggested, Likely, 1p out, AI, Sandbox), negative (red: Off
   track, over the limit), brand (cream tint: Awaiting payment, the Suggested action). Invoices' dark-brown Paid
   pill and Bank reconcile's brown Exact/Refund chips are gone; brown is for selection and primary actions. Used by
   Goals (`TONE_BADGE`), `invoices/LiveInvoices.tsx`, `bank/LiveBank.tsx`, `BankReconcile.tsx`, `BankFeeds.tsx`,
   `BankRules.tsx` and the Review card's confidence chip. Statuses and words unchanged.
6. **Review** (`review/ScanProgress.tsx`, `ProposalCard.tsx`). A finished scan with nothing failed folds into a
   compact cream row: headline, source, each file with where it went, Dismiss as a text button (still 44 px tall).
   Reading, waiting-to-confirm and failed files keep the full white card, bars and amber messages. The proposal
   card: supplier · amount heading at 22–24 px with tabular figures; confidence as a neutral badge with "Read by …"
   as quiet text; the facts and failed checks unchanged; the checker's "Why" and an agreeing verifier are 13–14 px
   muted; a disagreeing verifier keeps the amber box; the model line and ByWhom stay, lighter. No new dismiss or
   processing behaviour.
7. **Mobile** (`components/ProfileMenu.tsx`, `AppShell.tsx`, `app/globals.css`). Under 400 px the profile switcher
   shows one 13 px name line, the kind is `sr-only`, no chevron, and the button is `w-full` so it fills its
   shrinking wrapper and truncates with an ellipsis instead of running under the icons (a button is sized to its
   content whatever its display). Accessible name still "Profile: <name> <kind>"; still 44 px. Below 900 px the
   page's bottom padding is `9.5rem + env(safe-area-inset-bottom)` (the assistant button's top is 9 rem up; the
   tab bar is under it), and `html { scroll-padding-bottom }` matches, so a focused field or the last row of
   actions scrolls in above both — including when the on-screen keyboard shortens the viewport.

## Verified

- Screenshots of the built test-mode export at 320, 390, 768, 900, 1024, 1279, 1280 and 1440 px (full page), signed
  in with the sample-style books (bank seed, a posted receipt, three goals incl. a 77-character name and a
  £98.7 m target, four invoices incl. a 50-character customer and £1.2 m) and the `/try` demo; Goals and Review
  signed out; Home with empty books, a held `GET /books/home` (loading skeletons) and a 503 (error strip); the
  Record payment dialog at 320/390/1280; keyboard focus in the drawer, on a goal's View details and on Approve;
  the Review actions and the invoice form's end at 320×568 and 390×420 (keyboard-height viewports); the profile
  and account menus at 320/390. Every PNG was read; what was wrong and fixed: the profile name running under the
  icons at 320 (the `w-full` fix), the chart's clipped axis labels on seven-figure books, and the phone's first
  screen losing the Ask button when the ask bar moved below the tiles (moved back under the summary).
- `npm run lint`: clean. `npx tsc --noEmit`: clean (the LayoutProps error did not appear in this tree).
- e2e (test-mode runtime + export): home, dashboard, goals, review, invoices, invoice-payments, bank, bank-rules,
  bank-feeds, app-shell, keyboard, site-layout, submission-mode (banned words incl. "soon"), menu-pages,
  household-home, upload-flow, models, sample-books, signout-loading, phone, a11y (axe on every page at 390 px):
  282 passed on the first full run under heavy machine load; the 7 that failed were re-run alone — 6 pass
  (two were assertions that encoded the old order, updated in `e2e/home.spec.ts` and the ask bar's position; four
  were load timeouts). `signout-loading.spec.ts:6` ("sign out goes to the homepage") fails on this branch **and on
  the base commit 8debc2e9** (run in a detached worktree on its own ports): after Sign out the page lands on `/`
  with the signed-in shell's "Sign in again" bar over the sample Home instead of the landing hero. Pre-existing;
  nothing in this branch touches sign-out, `HomeSwitch`, `useSignedIn` or the landing.
- `scripts/prelaunch-words.mjs` on the diff: no "soon / coming soon / beta / launch" added; the e2e submission-mode
  spec passed on every rendered page.

## Not verified

- Why `signout-loading.spec.ts:6` fails on the base commit (outside this pass; it needs whoever owns sign-out).
- A real phone keyboard: the clearance was checked with shortened viewports (568 and 420 px tall), not with an
  on-screen keyboard; `scroll-padding-bottom` is what keeps a focused field above the fixed bars in that case.
- The 900–1279 px bar wraps to two rows at 1024 px when the profile name and email are long (pre-existing; the
  review's items did not cover it and the routes/structure were not to change).
- Dark backdrop contrast of the brass bar in the sidebar was eyeballed in the screenshots, not measured.

## Re-taking the screenshots

`UI_POLISH_SHOTS=1 UI_POLISH_TAG=<tag> pnpm exec playwright test e2e/ui-polish-shots.spec.ts --project=desktop`
(after `pnpm run e2e:build`) writes the full set to `/tmp/ui-polish-shots/<tag>/`; skipped from the normal run.

## Screenshots (this folder)

`home-order-390.png`, `home-order-1280.png` (year to date → Goals with the note → Trend and cash), `nav-vat-1280.png`
and `nav-vat-1024.png` (Reporting and Tax marked quietly on /vat), `invoices-badges-1280.png` (overdue amber, Paid
green, Sent brand tint, Draft grey), `review-card-1280.png` (the quiet finished scan and the card), `phone-bar-320.png`
(one profile line), `phone-form-end-320.png` (the form's last button and footer clear of the tab bar and button).
