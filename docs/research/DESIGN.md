# Design research: navigation, onboarding, review flows and brand for Accnomos

Written 28 Oct 2026 on branch `claude/research-design`. This covers part A (research) and the plan for part B (the
first three low-risk visual changes, which this branch makes). The screenshots of the app before and after those
changes are in [`design-shots/`](design-shots/): test-mode build, signed out (the labelled fictional sample) unless the
name says `signed-in`, captured at 1280 × 800 and 390 × 844 by `apps/web/e2e/design-shots.spec.ts`.

**How the research was done.** The sources are public pages: product sites, help centres, app-store listings, brand
guidelines and designers' write-ups. Nobody logged in to any of the products. Several hosts (xero.com, linear.app)
could not be fetched directly from this session, so those pages were read through a search index instead. Anything
that could not be traced to a public page is marked *unverified*. The empty-state designs of the benchmark apps
could not be checked without logging in or paying for a screen library, so the empty-state section draws on
principles and on Accnomos's own screens.

**Who owns what.** The `claude/profiles` branch owns the menu restructure and `claude/marketing` owns the landing
page. This document recommends both, but this branch changes neither.

---

## 1. What works in the best finance apps (2025–2026)

### 1.1 Navigation and information architecture

| App | Top-level structure (web) | Phone | Source |
|---|---|---|---|
| **Xero** (2025–26 refresh) | **Home, Sales, Purchases, Reporting, Accounting, Tax, Payroll, Contacts**. In the refresh Reporting moved into the main bar and Settings can be reached from every dropdown. A right-hand panel that is always present holds JAX (the AI), search, help and notifications. The exact order varies by region and plan (*unverified*). | Navigation groups match desktop, plus a new **'+'** button and a **Menu** tab (iOS v10.98.1). The exact tab labels are *unverified*. | [xero.com new navigation](https://www.xero.com/campaign/new-homepage-navigation/), [1st Formations guide](https://help.1stformations.co.uk/accounting-service/navigating-xero-the-key-areas-to-know), [App Store](https://apps.apple.com/us/app/xero-accounting-for-business/id441880705) |
| **QuickBooks Online** (Intuit platform UI) | A left rail: **+ Create, Bookmarks, Home, Feed** (an AI summary), **Reports, All apps**. Pinned apps (Accounting, Expenses, Sales by default) can be changed. Payroll appears at the bottom once added. | Tabs vary by plan and cannot be customised. Users complain about this. Reconciling is web only. | [QBO UK help](https://quickbooks.intuit.com/learn-support/en-uk/help-article/bookkeeping-processes/understand-navigation-menu-quickbooks-intuit/L310NeoHY_GB_en_GB), [community thread](https://quickbooks.intuit.com/community/other-questions-9/i-have-two-business-subscriptions-and-the-menus-in-the-app-are-completely-different-how-do-i-customize-the-top-and-bottom-menus-in-the-mobile-app-90939) |
| **FreeAgent** (UK) | Tabs: **Overview, Contacts, Work** (invoices), **Accounting, My Money, Banking**. A Taxes tab is likely; the exact label is *unverified*. | Home tiles that can be reordered: **Admin to-do list, Money in and out, Cashflow, Operating profit, Tax Timeline**. | [Overview screen](https://support.freeagent.com/hc/en-gb/articles/115001218610-An-introduction-to-the-Overview-screen), [mobile home](https://support.freeagent.com/hc/en-gb/articles/8624609196946-Reorder-the-home-screen-on-the-FreeAgent-mobile-app) |
| **Wave** | **Create new, Dashboard, Sales & Payments, Purchases, Receipts, Accounting, Banking, Payroll, Reports** | Bottom tabs **Dashboard, Sales, Accounting, Payments**. Create and Scan receipt sit in the top bar. | [Wave overview](https://support.waveapps.com/hc/en-us/articles/32453204338324-Overview-of-your-Wave-account) |
| **Tide** (UK) | Web navigation was aligned to the app. Settings moved to their own user area. Small tasks open in side sheets on web and bottom sheets on the phone. | Account and Pay were merged into **Payments**, and **Finance** was added. **"More" was removed**: Tide's research found an 80–90 % discoverability failure behind it. | [Tide update](https://www.tide.co/blog/tide-update/managing-your-business-is-easier-in-our-updated-tide-app/), [Tide design system write-up](https://james-sc.co.uk/tide-portal-design-system/) |
| **Mercury** | A sidebar: Home, Transactions, Payments, Cards, Invoicing, Accounting, Insights, Settings. The order is *unverified*. | Home first, Payments (⇄) in the centre. The Task Feed sits under the balance graph. | [Task Feed](https://support.mercury.com/hc/en-us/articles/28769957843732-Managing-tasks-in-your-Task-Feed) |
| **Revolut Business 5** | A home screen of widgets, an **Inbox** for approvals, and simpler navigation | Widgets, Inbox, approve or reject a request | [RB5](https://www.revolut.com/business/rb5/), [Applode flows](https://applode.ai/apps/ios/revolut-business/) |
| **Pennylane / Qonto** | Menus by job (Transactions, Purchases, Sales; *Pilotage* for the cash plan). Qonto removed its Quick Actions bar to declutter. | Qonto puts a **Scan receipt** shortcut on Home. | [Pennylane nav](https://help.pennylane.com/fr/articles/73795-naviguer-dans-pennylane-gestion), [Qonto](https://support-it.qonto.com/hc/en-us/articles/30022106575761-What-happened-to-the-Quick-Actions-feature-on-my-Qonto-interface) |
| **Linear** (benchmark for polish) | An "inverted L" frame. The March 2026 refresh **dimmed the sidebar** so content stands out, softened the borders, used fewer icons and made headers consistent. | Bottom toolbar (Oct 2025) | [Linear redesign](https://linear.app/now/how-we-redesigned-the-linear-ui), [2026 refresh](https://linear.app/changelog/2026-03-12-ui-refresh) |

**What we take from it**

1. **Group the menu by job, not by feature.** Xero's eight groups are the vocabulary UK owners and bookkeepers
   already know. Accnomos's current sidebar groups (Books / Money / Work) are its own invention: "VAT return" sits under
   Money, and Contacts sits under Work.
2. **One task inbox on Home.** Examples are Xero's Tasks widget, Mercury's Task Feed, FreeAgent's admin to-do list,
   and the Inbox in Ramp and Revolut. Accnomos already has the best possible content for this, the Review queue,
   but Home shows it as a tile far down the page.
3. **A global "+" or Create** (QuickBooks, Xero mobile, Wave, FreeAgent). For Accnomos the most frequent creation is
   *add a receipt*.
4. **No "More" catch-all on the phone** (Tide's measurement). Xero's 2026 **Menu** tab is the acceptable form of it:
   it opens the same named groups as desktop, so nothing is hidden behind a vague label.
5. **Make tax a timeline.** FreeAgent's Tax Timeline (HMRC and Companies House dates, file or mark paid from the
   card) is the most UK-specific good pattern in the set. Accnomos's Deadlines tile is a start.
6. **Dim the frame and let the content contrast** (Linear 2026). Use a few weights and sentence case. Intuit's type
   guide says 3–5 weights per page at most ([Intuit type](http://design.intuit.com/quickbooks/brand/design-foundations/type/)).

### 1.2 Reviewing and approving items

- **Suggestion plus one-tap accept, with fallbacks.** Xero's bank reconciliation shows a suggested match and you press
  **OK**; otherwise *Find & match*, *Create* or *Transfer* ([guide](https://xero-help.caltrix.asia/en/articles/12699545-how-to-use-the-xero-mobile-app-for-on-the-go-accounting)).
  Pennylane offers a one-click match, with search as the fallback and **Détacher** to undo
  ([Pennylane](https://help.pennylane.com/fr/articles/230727-questions-frequentes-sur-le-rapprochement-automatique-des-factures-et-des-transactions)).
- **Bulk approval of confident items.** FreeAgent's *Guess* explanations are approved in bulk
  ([FreeAgent](https://support.freeagent.com/hc/en-gb/articles/4405955565842-Get-started-with-FreeAgent)), and Qonto has a
  "To verify" view with *Mark as verified* ([Qonto](https://support-fr.qonto.com/hc/en-us/articles/23947645281681-How-to-review-my-transactions-for-accounting)).
- **A way to reach zero.** Qonto's *not required / lost* and Pennylane's *Facultatif* let the queue actually empty.
- **Nothing is shared until the user confirms.** Ramp's camera-roll receipt matching works this way
  ([Ramp mobile](https://support.ramp.com/ramp-mobile-app)). Ramp's users also show the failure to avoid: auto-match
  that submits before the coding is reviewed ([community](https://community.ramp.com/t/auto-match-receipts-stop-workflow/1337)).
- **Show status inline and the detail in a side panel.** Qonto's table has Attachments, VAT and Verification
  columns, and Pennylane and Tide open the detail in a side sheet.

Accnomos already does the hard parts: a confidence score, a second reading compared field by field by code, 12
checks by code, Undo, approval of rule matches in bulk, and J/K/A/E/R/U shortcuts. The design job is to make that
visible in the first two seconds of looking at a card (section 4).

### 1.3 Onboarding

- **FreeAgent:** about you → connect your bank (with *Connect later*) → bank set-up → verify your email
  ([FreeAgent set-up](https://support.freeagent.com/hc/en-gb/articles/115001218550-Set-up-your-FreeAgent-account)). It is
  short, and every step can be skipped.
- **Xero:** a getting-started hub (organisation → bank → invite an adviser). The exact steps are *unverified*
  ([Xero get started](https://www.xero.com/us/get-started/)).
- **Tide** (payments): **smart defaults from behaviour**. 46 % of payments went to one of the last three
  recipients, so the list gets a "Recent" section; the main account is pre-selected; "send once" is the default
  ([Tide payments](https://james-sc.co.uk/tide-payments/)).
- **GOV.UK:** one question per page, only ask for a piece of information once, mark optional fields "(optional)",
  and always offer a Back link ([question pages](https://design-system.service.gov.uk/patterns/question-pages/)).

### 1.4 Visual identity in the category

| Brand | Colour | Type | Notes |
|---|---|---|---|
| Xero | Midnight **#000856** (Xero says 9.65:1 on light), XUI Blue **#1F65D6**, Xero Blue **#3ECCFF** | *unverified* | [roundel guidelines 2024](https://brandfolder.xero.com/NE531UQB/as/3kfmkhrbbq3h7cxpg3xc8t45/639193-xero-roundel-logo-guidelines-2024) |
| QuickBooks | Green **#2CA01C** (Intuit itself says it is "not accessible on all backgrounds") | Avenir Next for Intuit, sentence case, 4 px grid | [Intuit type](http://design.intuit.com/quickbooks/brand/design-foundations/type/) |
| Revolut | Deep Blue **#1326FD**, Lime #BFFF37, UI black #161618 | Aeonik Pro | Voice: jargon cut out, "a bit of wit" ([Revolut OB guidelines](https://developer.revolut.com/assets/oba/Revolut-Open-Banking-guidelines.pdf)) |
| Monzo | Hot coral, deep navy, soft white | Oldschool Grotesk (hero), Monzo Sans (UI) | Business has its own pot imagery ([Monzo](https://monzo.com/blog/weve-had-a-little-makeover)) |
| Ramp | A lime highlight colour (hex *unverified*) | TWK Lausanne + Burgess (serif) | "Dramatic sense of scale" ([Red Antler](https://www.redantler.com/work/ramp)), a "bento" grid of product graphics ([Bakken & Bæck](https://bakkenbaeck.com/case/ramp)) |
| Pennylane | Green, chosen because it "recalls Excel" | lowercase wordmark | [Maddyness](https://www.maddyness.com/2022/04/14/pennylane-qonto-imagine-identite-visuelle/) |
| Qonto | Black (it dropped violet in 2022), plus a vibrant secondary palette from 2025 | *unverified* | [Maddyness](https://www.maddyness.com/2022/04/14/pennylane-qonto-imagine-identite-visuelle/) |
| Starling | "Richer purple and electric teal" (Sep 2025) | new fonts (*unverified*) | [Starling branding update](https://www.starlingbank.com/about/branding-update/) |

**Where Accnomos sits.** Deep teal on warm paper is not used by any of the big UK players. Xero is navy and blue,
QuickBooks green, Tide navy, Monzo coral, Revolut blue, and Starling has just moved to purple with *electric* teal.
Accnomos's teal is calmer and darker than Starling's. Keep it: it reads as "ledger and paper", fits the
"stored only by you" promise, and already passes AA everywhere it is used as text (section 6.2).

### 1.5 WCAG 2.2: the new success criteria that matter here

Source for the criteria: [W3C, What's new in WCAG 2.2](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/).

| Criterion | What it means for Accnomos | Status |
|---|---|---|
| **2.4.11 Focus Not Obscured (AA)** | The sticky phone header, the bottom tab bar and any sticky Approve bar must never fully cover the focused element. | Add `scroll-padding` the height of the tab bar and the header (change 9). |
| **2.5.7 Dragging Movements (AA)** | A dashboard you can rearrange, or drag-to-match a receipt onto a bank line, needs a single-pointer alternative. | Nothing drags today; keep it that way, or add Move up/down buttons. |
| **2.5.8 Target Size (AA)** | Targets at least 24 × 24 CSS px, or spaced so they don't overlap. | Nav items are 44 px high. The **"?" help buttons are about 28 px**, which passes. Check the table row actions and checkboxes on Bank. |
| **3.2.6 Consistent Help (A)** | Help sits in the same relative place on every page. | The "?" sits at the right of every page header: good. Keep "How it works" in the footer of every page. |
| **3.3.7 Redundant Entry (A)** | Don't ask twice in one process. | Prefill the VAT number and business name from Settings into invoices and the HMRC flow. |
| **3.3.8 Accessible Authentication (AA)** | No memory test at sign-in. | Microsoft sign-in (MSAL) handles this; never block pasting into HMRC test-user fields. |
| *1.4.11 Non-text Contrast (2.1, still the weakest point)* | Form-field borders need 3:1 against their background. | `--color-border` #e3e1d8 is **1.31:1 on white**. It is fine for card edges but fails on inputs. Proposed `--color-border-strong` **#7a776c (4.48:1)** for inputs (change 8). |

GOV.UK and HMRC money inputs: `type="text"` with `inputmode="decimal"`, the **£ prefix outside the field**, "in
pounds" in the label, accept "£1,234.50" as typed, and give specific errors ("must include pence, like 123.45")
([HMRC currency input](https://design.tax.service.gov.uk/hmrc-design-patterns/currency-input/),
[GOV.UK text input](https://design-system.service.gov.uk/components/text-input/)).

### 1.6 What makes a 3-minute hackathon demo read well on screen

- **Record at 1280 × 720 with 125 % zoom for close-ups** (as `docs/submission/VIDEO_SCRIPT.md` already says), and watch a test
  clip *on a phone* before publishing ([SSW rules](https://www.ssw.com.au/rules/easy-to-view-screen-recordings),
  [Honeycutt](https://www.honeycutt.com/posts/recording-guidelines-to-make-your-demos-sparkle)).
- **Use the light theme with high-contrast text.** Dark mode suffers most from video compression (Honeycutt).
- **Make the key numbers large.** Body text of about 15–16 px survives compression to 1080p, but the figure the
  voice-over names (Box 4 £8.65, £120.00) should be **28 px or more** and tabular.
- **Zoom about 2× on the action, eased, and hold still while the viewer reads.** Don't zoom on every click
  ([Nook](https://usenook.live/blog/demo-video-best-practices)).
- **Pace: problem → promise → three actions → result → call to action**, about half a second of stillness after each
  click, and speed up the waits with a caption ([demoeditor](https://demoeditor.com/articles/how-to-record-a-product-demo)).
- **The first frame matters most.** A judge decides in the first 10–15 s whether the product is real. That frame
  should show your figures and the "AI proposes · you approve · code calculates" promise, not a set-up checklist.

---

## 2. Recommended menu structure for Accnomos (for `claude/profiles`)

### 2.1 Desktop (signed in): Xero-like groups as a top menu or sidebar

Labels are the ones UK users know from Xero. Each group lists the existing pages it absorbs; *(new)* marks pages
that do not exist yet and should not be shown until they do.

| Group | Contains (existing route) | Notes |
|---|---|---|
| **Home** | Dashboard `/`, **Review** `/review` (with badge), Ask `/ask` | Review stays one click from everywhere: it is the product. Ask is also the bar at the top of Home. |
| **Sales** | Invoices `/invoices` (incl. credit notes, payments), Jobs & timesheets `/jobs` | Quotes *(new)* later. |
| **Purchases** | Bills & receipts (Review filtered to purchases), Mileage `/vehicles` | "Add a receipt" is the main action here. |
| **Reporting** | Reports `/reports` (P&L, aged, VAT by period, trend), Audit trail `/audit` | |
| **Accounting** | Bank `/bank` (Reconcile, Rules), Files `/files`, chart of accounts *(new)* | Bank sits here as in Xero. |
| **Tax** | VAT return `/vat`, HMRC connection, Deadlines (from Home) | A FreeAgent-style tax timeline later. |
| **Payroll** | Pay runs `/payroll`, Staff (from Jobs) | |
| **Contacts** | `/contacts` (Customers, Suppliers, Possible duplicates) | |
| **Personal** *(personal profiles only)* | `/personal` (budgets, regular bills, savings goals) | Replaces Sales/Purchases/Payroll for a personal profile: **Home, Personal, Reporting, Tax, Contacts**. |
| *Right-hand utilities* | Settings, profile switcher, help "?", search | Settings reachable from every group, as in the Xero refresh. |

A **sole trader** profile hides Payroll until staff exist. A **personal** profile shows only the five groups above.

### 2.2 Phone: bottom tabs, with a Menu sheet instead of a drawer

**Tabs (4 + 1):** **Home · Review (badge) · [＋ Add] · Tax · Menu**

- **＋ Add** (centre, raised teal button) opens a bottom sheet: *Photograph a receipt*, *Upload a file*, *New invoice*,
  *Record mileage*. This is Xero's '+', Wave's Scan, Qonto's Scan receipt.
- **Menu** opens a full-height sheet listing the **same named groups as desktop**, with search. It is not a "More"
  list of leftovers: Tide's 80–90 % failure applied to an unnamed catch-all, not to a mirror of the desktop groups.
- **Why not a drawer (hamburger):** it hides the badge count and needs two taps for Review, the most frequent task.
- **Ask** becomes a bar on Home (it already is) and an action in the + sheet. Today's tab bar (Home, Review, Ask, VAT,
  Files) gives two of five slots to things that are not daily tasks.
- Labels at **12 px minimum**, with an icon above each. The current 11 px text-only tabs are hard to read on video.

---

## 3. Onboarding flow

Today: `/connect` → create the folder → *Choose your AI* → a 7-step "Get set up" checklist on Home. All 7 steps
appear before any figure (screenshot `home-signed-in-390-before.png`: the checklist fills the phone screen).

**Recommended** (one question per screen, every step skippable, about 2 minutes):

1. **Who are these books for?** Limited company · Sole trader · Personal. This sets the menu profile (section 2.1).
2. **Connect your OneDrive.** One button, plus one sentence: "Your books are files in your folder. We keep no copy."
3. **Choose your AI.** *On my own machine (Muse Glimmer)* or *My Meta API key*, then **Test connection**, with a
   friendly result.
4. **Your business:** name and VAT number. The number is checked by code, and HMRC lookup comes later. Prefill
   wherever we can (3.3.7).
5. **VAT period:** quarterly stagger, shown as three calendar chips ("Mar · Jun · Sep · Dec"), not as a stagger
   number.
6. **Try it now:** "Scan the sample receipt" goes straight to Review with one proposal waiting. This is the "aha".
   Alternatively, **Load sample books** for six months of fictional data.

After onboarding, Home shows the remaining optional steps (Invoice profile, Outlook contacts) as a **thin progress
bar with a count** ("2 of 7 · Continue set-up"), not a 7-row list above the figures.

## 4. The review-and-approve card pattern

What a card should say, in reading order (the bold items should be visible without scrolling at 390 px):

1. **Supplier · total** as the title, for example **Screwfix · £38.47**. This is already right.
2. **Three figures in one row at a larger size:** Net · VAT · Total, tabular, with the date beside them.
3. **One trust line:** "✓ 2 readings agree · 12 of 12 checks by code". Teal when everything passes, amber with the
   failing check named when something doesn't. The confidence percentage is secondary (tooltip or a small pill).
4. **The document thumbnail** on the left at desktop, above the figures at the phone (tap to open the viewer). Its
   frame should be the same height as the text block, not 200 px of "No image".
5. **The account and VAT code** as editable chips ("Tools & small equipment · VAT S"), with "Why?" folded away.
6. **One primary button: Approve (post to books).** Secondary: Edit, Reject. *Always do this for {supplier}* is a
   checkbox beside Approve. Undo appears as a toast for 8 s after approval, plus `U`.
7. **Bulk approval lives in one place:** the "N proposals match rules you saved · Approve all" banner above the list.
   Today the same button also appears inside each matching card (`review-1280-before.png` shows it twice), which
   makes the first screen look repetitive.

On phone, the card's actions sit in a sticky bottom bar **above** the tab bar, with `scroll-padding-bottom` so the
focused field is never hidden (2.4.11).

## 5. Empty states and dashboard layout

### 5.1 Empty states

The shared `EmptyState` (`src/components/States.tsx`) is already consistent: an icon, a title, one sentence and one
action. Rules for every page:

- **Say what will appear here and how to make it appear**, then give exactly one button. For example: "No receipts
  waiting. Forward receipts to your Accnomos inbox or add one now. [Add a receipt]".
- **Offer the sample**: "or see this page with the fictional sample books". Judges can then see a full page without
  setting anything up.
- **Celebrate zero where zero is good.** Review empty means "All caught up: nothing waiting for you", with a small
  teal tick. Don't use the same icon for "empty" and "done".
- **Never show an empty chart.** Show the axis with one sentence instead.

### 5.2 Dashboard (Home) layout

Following Xero's homepage, Mercury's balance plus task feed, and FreeAgent's overview, top to bottom:

1. **Greeting and the four figures** (Cash in bank · Owed to you · Owed by you · VAT estimate), large and tabular,
   in the first screen at 1280 and at 390.
2. **"N waiting for you"**: the Review queue as the single task inbox, with the first two items inline and
   "Review all".
3. **Deadlines** as a tax timeline (VAT due, payroll), each with its action.
4. **Ask bar.**
5. Secondary: inbox triage, plan today, recent activity.
6. **Set-up progress** as a one-line bar until it is dismissed.

At ≥1280 px, use a 3-column grid over about 1,000 px of content width. Today the content is capped at 768 px, so at
1280 the Home grid and the VAT table are squeezed between about 140 px of empty margin on each side
(`vat-1280-before.png`: "VAT due on sales" wraps onto two lines).

---

## 6. Brand direction (refined)

### 6.1 Logo usage

- **Mark:** the hexagon-and-tick (a ledger cell plus approval) in paper `#F4F3EE` on a teal rounded square. Use the
  mark alone at 36 px and above in the app, and the mark plus the "Accnomos" wordmark (Manrope ExtraBold, −1 %
  tracking) in the header and sidebar.
- **Clear space:** at least half the mark's width on every side. **Minimum size:** 24 px for the mark, 96 px wide for
  the lockup.
- **On dark** (the sample banner, video end cards) use the reversed version: a teal-tint square with a teal-dark tick.
- **Don't** recolour it to Meta blue, add gradients, or place it on the hero illustration. Brand art from Muse Image
  (`tools/brand_muse.py`) stays illustration and is never the logo.

### 6.2 Colour palette, with measured contrast

Ratios are WCAG 2 relative-luminance contrast, measured for this document against the app's real backgrounds.

| Token | Hex | Role | on white | on ground #F4F3EE | on teal-tint #E6F1EF |
|---|---|---|---|---|---|
| `ink` | #1B1F24 | Text, the sample banner | **16.56** | 14.91 | 14.35 |
| `teal` | #0F6E63 | Primary buttons, the brand | **6.12** | 5.51 | 5.30 |
| `teal-dark` | #0A4F47 | Links, focus ring, button hover | **9.45** | 8.51 | 8.19 |
| `muted` | #4B5159 | Secondary text | **8.01** | 7.21 | 6.94 |
| `amber` | #B45309 | Overdue, Review badge (white text on it 5.02) | **5.02** | 4.52 | **4.35 ✗** |
| `warn-ink` | #8A3F06 | Warning text on warn-bg | 7.52 | 6.76 | 6.51 |
| `border` | #E3E1D8 | Card edges (decorative only) | 1.31 | 1.18 | — |
| *proposed* `border-strong` | #7A776C | Input and checkbox borders (1.4.11 needs 3:1) | **4.48** | 4.04 | — |
| *proposed* `positive` | #166534 | "Agrees", paid, reconciled | **7.13** | — | — |
| *proposed* `danger` | #B42318 | Errors, failed checks | **6.57** | — | — |

White text on `teal` buttons is 6.12:1 (AA for every size). **Rule: never set `amber` text on `teal-tint`**
(4.35:1). Use `warn-ink` there instead. The palette stays deliberately narrow: one brand colour, one warning
colour, and neutrals warmed towards paper.

### 6.3 Type scale (Manrope, already loaded)

Use four weights at most per screen (400, 600, 700, 800), sentence case everywhere except the small uppercase
eyebrow labels, and **tabular figures for every amount**.

| Step | Size / line height | Weight | Use |
|---|---|---|---|
| Display | 36–40 / 1.1 | 800 | Landing hero only |
| H1 | 30 / 1.2 | 800 | Page titles ("Review", "VAT return") |
| **Figure** | **30 / 1.1, tabular** | 800 | Home figures, VAT Box 5, card totals: what the narrator reads out |
| H2 | 18–20 / 1.3 | 800 | Card titles |
| Body | 15–16 / 1.6 | 400–600 | Text, table cells |
| Small | 13 / 1.5 | 600 | Captions, sub-lines under figures |
| Micro | 12 / 1.4 | 700–800 | Pills, tab labels, eyebrow (uppercase, +8 % tracking). Never below 12 px. |

### 6.4 Iconography

A single 20 px line set with a 1.75 px stroke, round caps and round joins, the same as the existing logo and empty-state
glyphs (Lucide's geometry is a free match). Pair every icon with a label, apart from the universal "?" and ×. The
icon itself carries no colour: teal only for active nav items or a confirmed state.

### 6.5 Tone of voice

Plain, first person plural, UK English, and calm. Name the thing and the next step. The brand line is
**"AI proposes · you approve · code calculates."** Use it on Home, Review and the video's first and last frames.
Today Home leads with "Books read by AI. Approved by you. Stored only by you." and Review with "…code posts", so the
three wordings should become one.

- Do: "2 receipts are waiting for you." "Box 4 is worked out by code from the entries you approved."
- Don't: "Oops!" or "AI magic". Never say "the AI decided".
- Money words: VAT return, MTD, net / VAT / total, *owed to you* / *owed by you* rather than AR/AP.

### 6.6 Motion

- **150–200 ms ease-out** for state changes. The existing VAT box fade (250 ms) is the model.
- **Approve:** the card slides up and fades (200 ms), the "N waiting" count ticks down, and an Undo toast stays
  for 8 s.
- **Figures** don't count up (that reads as gimmicky in finance). They fade in when data lands, with the skeleton
  reserving the space (this already happens).
- Everything is honoured by the existing `prefers-reduced-motion` rule in `globals.css`.

---

## 7. Ten concrete before/after changes, ranked by impact on a judge's first 60 seconds

"Risk" means the risk to the existing e2e suite and to the other branches. Changes 1, 2 and 4 belong to other branches
or touch structure, so the first three **low-risk** changes (★) are the ones this branch makes.

| # | Before | After | Risk / owner |
|---|---|---|---|
| 1 | Signed-in Home opens on a 7-row "Get set up" list; the figures start below the fold at 1280 and 390 (`home-signed-in-*-before.png`). | The figures and "N waiting for you" come first; set-up becomes a one-line progress bar ("2 of 7 · Continue"). | Medium: it reorders Home components; `home.spec.ts` and the empty-state specs assert the order. |
| 2 | Sidebar groups Books / Money / Work with 12 flat links; phone tabs Home · Review · Ask · VAT · Files at 11 px, text only. | Xero-like groups (section 2) and phone tabs Home · Review · ＋ · Tax · Menu with icons. | **Owned by `claude/profiles`.** |
| **3 ★** | **Content is capped at 768 px.** At 1280 there are about 140 px of empty margin on each side, the VAT table wraps "VAT due on sales" onto two lines, and the Home grid's 3 columns are squeezed. | **Content is up to 1,024 px wide from 1280 px up** (phones and tablets unchanged). The VAT table reads on one line per box, and Home's three columns breathe. | Low: one class in `AppShell`. **Done on this branch.** |
| 4 | The landing pitch is three stacked claims plus two Connect buttons on the same screen. | One promise ("AI proposes · you approve · code calculates"), one primary CTA, and "See the demo books" as the secondary. | **Owned by `claude/marketing`.** |
| **5 ★** | **The Home figures are 24 px**, the same weight as the card titles, so the money doesn't stand out on video. | **The figures are 30 px from 640 px up (28 px on phones)**, tabular, with a tighter line height: the number the narrator says is the biggest thing on screen. | Low: classes in `Tiles.tsx`. **Done on this branch.** |
| 6 | The Review card shows "Approve all 2 rule matches" in the banner *and* inside each matching card; a 200 px grey "No image" box sits beside the figures. | Bulk approval appears only in the banner; the card shows Net · VAT · Total large, with one trust line ("2 readings agree · 12 of 12 checks"). | Medium: changes Review markup, and the review specs click those buttons. |
| **7 ★** | **On a phone, "Get set up" wraps its Dismiss button onto its own line** under the subtitle (`home-signed-in-390-before.png`), which reads as broken layout. | **Dismiss stays top-right beside the title at every width**; the subtitle wraps under the title instead. | Low: classes in `SetupChecklist.tsx`. **Done on this branch.** |
| 8 | Input borders use `border` #E3E1D8 (1.31:1 on white, which fails 1.4.11); there is no `positive` or `danger` token, so hexes are hard-coded (e.g. `#0A4F47` in `Pitch.tsx` and `States.tsx`). | Add `border-strong` (#7A776C, 4.48:1), `positive` and `danger` tokens; inputs use `border-strong`; hard-coded hexes become tokens. | Low to medium: touches many files; best done when no other branch is mid-flight. |
| 9 | The signed-out nav shows a Review badge of **1** while the Review page says **"4 waiting for you"**; the phone page header leaves the "?" alone on its own line. | The badge uses the sample's real count; the page header keeps the "?" on the title row at every width; `scroll-padding` covers the sticky header and the tab bar (2.4.11). | Low to medium: the badge is in `AppNav` (`claude/profiles`); Ask's header action is long text, so the header needs care to avoid overflow at 390 px. |
| 10 | Approving a card swaps the content instantly; the brand line differs between Home ("Stored only by you") and Review ("…code posts"). | A 200 ms slide-and-fade on Approve, with the count ticking down and an Undo toast; the same brand line on Home, Review and the video's end card. | Medium: motion has to stay deterministic for the e2e timing; the copy is covered by assertions in several specs. |

### What this branch changed (part B)

- **Change 3:** `src/components/AppShell.tsx`. The main column and footer go from `max-w-3xl` to
  `max-w-3xl xl:max-w-5xl`.
- **Change 5:** `src/components/home/Tiles.tsx`. The figure is now `text-[28px] sm:text-3xl leading-tight`
  (it was `text-2xl`).
- **Change 7:** `src/components/home/SetupChecklist.tsx`. The header no longer wraps (`flex-wrap` removed, the title
  block is `flex-1`), so Dismiss keeps its place.

After screenshots: `design-shots/*-after.png` (same pages, same sizes). The existing e2e suite is unchanged and
passes: 226 passed, 0 failed, 94 skipped (the gated screenshot specs), 9.6 min with CI=1 on 3 workers; eslint and tsc are clean.
