# Home dashboard and navigation research

- **Date:** 28 October 2026
- **For:** Accnomos (UK AI bookkeeping and MTD app for businesses, sole traders, landlords and personal finances)
- **Scope:** how Xero, QuickBooks Online (QBO), FreeAgent, Sage Accounting and Dext lay out the signed-in home page and their navigation; public UX guidance on dashboards, sub-navigation and accessible charts; recommendations for the Accnomos home dashboard, navigation and AI summary.

**Method and limits.** The built-in web fetcher could not resolve any vendor host from this session (central.xero.com, blog.xero.com, quickbooks.intuit.com, support.freeagent.com, www.freeagent.com, help.sbc.sage.com and help.dext.com all failed DNS). Pages were therefore read through the Exa fetch service. Sources marked **(full page read)** were fetched in full. Sources marked **(search excerpt only)** were seen only as excerpts in search results, so treat them as weaker evidence. The UK QBO "Introduction to the Home dashboard" article timed out, so the global-English QBO help article stands in for it. No vendor UI was inspected directly, so there are no screenshots. Everything below comes from vendor documentation.

---

## 1. Xero

**Dashboard layout (new homepage, rollout from 25/26 Nov 2025 to March 2026).** Xero describes the new homepage as a move "from the classic dashboard to a more insightful and actionable command centre". Each widget is framed as the answer to a question:
- *Are we making a profit?* A new **net profit or loss** widget breaks down income and expenses for a period the user chooses.
- *How much money is in the bank?* A **bank accounts** widget shows balances **and reconciliation status**, so you can see whether the Xero balance matches the bank.
- *How much money do I owe?* A **bills to pay** widget shows due and overdue bills and has one-click "add bill".
- *Can we afford to pay our bills?* A **cash in and out** widget shows a 6-month trend, with a hover breakdown for each month.
- *How much money is owed to me?* An **invoices owed to you** widget.
- *Have I been paid?* A new **recent invoice payments** list.
- Also a **chart of accounts watchlist** for tracking against monthly budget, and a new **tasks list** widget for outstanding invoices and bills, which turns the homepage "into a true action hub".
- **Customisation:** drag and drop to show, hide and reorder widgets; up to **four columns**. Layouts are **per user** and do not change what colleagues see. A secondary source says widgets can be resized and layouts saved per screen size (CFOtech, search excerpt only).
- **Change management:** for a while users could switch back to the classic dashboard for 24 hours at a time.

**Navigation.** Xero uses a **top horizontal bar with drop-downs**. Since roughly September 2025 its main sections are Home, Sales, Purchases, Reporting, Payroll, Accounting, Tax (with regional menus and permissions) and Contacts. Each drop-down ends with a link to that area's settings, and there is also a central settings page. A **right-hand panel** holds JAX, search, help, notifications and apps.

**AI.** JAX ("Just Ask Xero") is described as an "AI financial superagent". It is conversational, answers questions about your own data using charts and tables, combines Xero data with public web data, and can take actions such as creating invoices. It also works through WhatsApp, SMS and email. Xero's vision page calls this "Accountable Intelligence … showing its work every step of the way". None of the pages I read describes a JAX-written narrative summary on the homepage itself.

**Notable for us:** each widget answers one question; bank balance sits next to reconciliation status; the tasks widget is on the home page; layouts are per user.

Sources:
- https://blog.xero.com/uk/product-updates/new-xero-homepage/ (published 25/26 Nov 2025; full page read)
- https://www.xero.com/uk/ai-in-accounting/jax/ and https://www.xero.com/uk/ai-in-accounting/jax-vision/ (checked 28 Oct 2026; search excerpt only)
- https://www.xero.com/uk/guides/ai-agent-accounting/ (21 Aug 2026; search excerpt only)
- Xero navigation guide PDF, brandfolder.xero.com "Your guide to Xero's refreshed navigation" (checked 28 Oct 2026; search excerpt only)
- https://lnonline.com.au/pages/xero-interface-changes (third party, says the change dates from mid-September 2025; search excerpt only)
- https://help.1stformations.co.uk/accounting-service/navigating-xero-the-key-areas-to-know (third party, lists the 8 top sections; search excerpt only)
- https://cfotech.co.uk/story/xero-unveils-customisable-homepage-packed-with-widgets (search excerpt only)

## 2. QuickBooks Online (UK / global help)

**Dashboard layout (Home).** From top to bottom:
- **App carousel**
- **Create actions:** up to 10 shortcuts. If the user does not choose them, QBO picks them over time.
- **Intuit Intelligence chat bar:** "uses AI and your business data to provide instant answers and automate financial tasks".
- **Business at a glance** widgets:
  - **Bank Accounts:** bank, card and cash-on-hand balances, with link, reorder and hide-loan options
  - **Profit & Loss:** net profit over time with income and expenses
  - **Expenses:** spend over time by category
  - **Cash Flow:** money in and out
  - **Needs Attention:** top-priority items, "plus work we've already completed for you that's worth a quick review", resolvable inline, with a View all page
  - Search results also mention a Sales & Get Paid funnel and a Business Feed
- **Customisation:** you can add, remove, move and resize widgets, though some sections cannot be reordered and some widgets only resize one way.
- **Privacy toggle:** hides financial figures while the page is on screen.

**Navigation.** QBO uses a **left sidebar of icons with hover pop-out menus**. Items are +Create, Bookmarks, Home, Feed, Reports and All apps. Work is grouped into "apps" or hubs (Sales, Expenses, Accounting, Taxes, Reports, Payroll and so on). Users can pin apps; the UK help says up to three at the bottom of the sidebar. Bookmarks let users save individual pages such as P&L or Unpaid Invoices. The UK help also says VAT and Income Tax live under **Taxes** in My Apps, and that the new layout "makes it easier to see items marked 'Review Needed'" for MTD for Income Tax. There is a Classic View escape hatch.

**AI.** In the US help, **Feed** "shows an AI-generated summary of recent transactions and the state of your finances". In the UK help, the Feed is "powered by Intuit Assist" and raises smart suggestions (for example a possible duplicate invoice or a missing supplier). An Accounting Agent categorises transactions to HMRC categories, and users can ask questions from the search bar.

**Notable for us:** a "Needs attention" queue that includes **AI work to review**; a privacy toggle; bookmarks; a Review Needed state tied to MTD.

**Caution:** hover-activated sidebar menus go against NN/g guideline 13 (see section 6).

Sources:
- https://quickbooks.intuit.com/learn-support/en-global/help-article/product-setup/customize-home-page-quickbooks-online/L0ryPsyjD_ROW_en ("updated 3 weeks ago" at 28 Oct 2026; full page read)
- https://quickbooks.intuit.com/learn-support/en-us/help-article/bookkeeping-processes/understand-navigation-menu-quickbooks-online/L310NeoHY_US_en_US (updated 5 Aug 2026; full page read)
- https://quickbooks.intuit.com/learn-support/en-uk/help-article/migrate-services/changes-switching-quickbooks-self-employed-sole/L4LI1B5GD_GB_en_GB ("updated 7 months ago"; full page read)
- https://quickbooks.intuit.com/learn-support/en-uk/configure-products/an-introduction-to-the-home-dashboard/01/239740 (**unreachable**, timed out; seen as a search excerpt only, which mentions Home and Planner tabs)

## 3. FreeAgent

**Dashboard layout (Overview screen).** The Overview is made of panels that can be **reordered by dragging** the grey bar at the top of each panel:
- **Cashflow:** money in and out across all bank accounts over the last 12, 6 or 3 months. It uses **historical bank transactions only**. The help article explains that this differs from profit and from the separate 90-day Cashflow forecast, which does include open invoices and bills.
- **Invoice Timeline:** expected against received money each month, colour-coded overdue (red), due (amber) and paid (green). Each status can be toggled off.
- **Expenses:** out-of-pocket expenses and mileage from the last 90 days, plus the balance owed to the user.
- **Tax Timeline:** a calendar of tax dates and amounts (Self Assessment, VAT, Corporation Tax, payroll). You can filter by All, Upcoming or Paid/Filed, file or mark as paid directly from the timeline, and sync it to an external calendar. It warns that **Self Assessment projections use the previous year's rates** until FreeAgent updates its figures, and that dates may differ from HMRC or Companies House records.

**Navigation.** FreeAgent uses **top tabs with drop-down menus**, for example Banking > Cashflow, Accounting > Reports and My Money > Expenses. A bell icon by the business name opens **Radar**, which holds Insights and an admin to-do list where completed items get struck through.

**Insights.** These are notifications covering top customers, slowest-paying customers, top spending categories (compared with the same six months last year), upcoming VAT payments (raised if bank balances look too low to cover the VAT bill, with the caveat that the accounts may not be up to date) and the accounting year end. They need access level 7 or above. The 90-day Cashflow forecast also offers "smart suggestions" such as chasing an overdue invoice or paying a bill.

**Notable for us:** a tax timeline with actions on each row; honest labels on what each number includes and excludes; insights computed by rules, each linking to the underlying report.

Sources:
- https://support.freeagent.com/hc/en-gb/articles/115001218610 (checked 28 Oct 2026; full page read)
- https://support.freeagent.com/hc/en-us/articles/360000658464-Insights-in-FreeAgent (checked 28 Oct 2026; search excerpt only)
- https://support.freeagent.com/hc/en-us/articles/32250867556882-Business-planning-in-FreeAgent (checked 28 Oct 2026; search excerpt only)
- https://www.freeagent.com/blog/introducing-insights/ (9 Apr 2018; search excerpt only)
- https://www.freeagent.com/blog/pro-tips-to-help-you-squeeze-all-the-goodness-out-of-freeagent/ (8 Sep 2023; search excerpt only)

## 4. Sage Accounting (UK)

**Dashboard layout.** Sage uses **Summary dashboards** arranged as **tabs by business area**:
- **Sales:** trends, total outstanding, **oldest overdue invoices**, quotes pipeline, best customers, biggest debtors and VAT due on sales.
- **Purchases:** trends, amounts owed to suppliers, overdue purchases, spend by category, biggest creditors and reclaimable VAT.
- **Cash flow:** statement and forecast.

The marketing page says the dashboard covers cash flow, profit trends, labour costs and top customers, plus estimated carbon emissions. I did not find an official list of widgets or customisation options.

**Navigation.** The main navigation is "a row of tabs taking you to the major areas" (Getting started, 2020). A personal setting switches between **Standard** navigation (business terms such as Sales and Purchases, with reports under Reporting) and **Advanced** navigation (accounting terms such as Sales Ledger and Purchase Ledger, with an Accountant menu).

**AI.** **Sage Copilot** has been included in every plan since 30 Sep 2025. It follows up late invoices, and its **VAT assistant alerts you as deadlines approach**, checks the books for mistakes and calculates VAT owed before submission. It also surfaces "trends, risks and opportunities".

**Notable for us:** a choice between plain-English and accountant-style navigation labels; listing the oldest overdue items first; a VAT deadline assistant.

Sources:
- https://help.sbc.sage.com/en-gb/accounting/getting-started-with-accounting/real-time-view-business.html (last modified 13 Sep 2023; full page read)
- https://gb-kb.sage.com/portal/app/portlets/results/viewsolution.jsp?solutionid=222001000101215 (Navigation and data grids, last modified 25 Mar 2024; search excerpt only)
- https://gb-kb.sage.com/portal/app/portlets/results/viewsolution.jsp?solutionid=201106161629887 (Getting started, 2020; search excerpt only)
- https://www.sage.com/en-gb/sage-copilot/ and https://www.sage.com/en-gb/sage-business-cloud/sage-accounting/ (checked 28 Oct 2026; search excerpt only)
- https://www.sage.com/en-gb/company/digital-newsroom/2025/09/sage-empowers-small-businesses-and-accountants-with-ai-to-cut-admin-and-get-paid-faster/ (30 Sep 2025; search excerpt only)

## 5. Dext

**Dashboard layout (business account Overview, 17 Sep 2026).** Dext says this page is "your entry point into Dext, not a full reporting page". It contains:
- **To do**, split into **Needs your attention** and **Waiting on others**. Each item opens the relevant area with the list already filtered.
- **Business summary** (admins only): Costs incurred, Expense claims submitted and Sales recorded, each shown as value and count for the Current or Last complete Week, Month or Quarter. Costs incurred breaks down by Suppliers, Categories or Type.
- **Recent submissions** (standard users).
- **Get the most out of Dext:** credits left and features not yet used.
- What each person sees depends on their role.

The client-account Overview (10 Feb 2026) shows counts and status for Costs, Sales, Expense claims, Bank, Supplier statements and Approvals (for example Processing, To review, Ready), a workflow summary and, on some plans, a Health Score and VAT and Corporation Tax insights.

**Navigation.** A **left sidebar** with Overview, Costs, Sales, Bank and Vault in a business account; Clients, Insights, Workflows and Team at practice level. A top bar holds the client switcher. Within Costs and Sales, **tabs** separate Inbox, Processing, Approvals and Archive, with optional To review and Ready tabs.

**Notable for us:** the split between "Needs your attention" and "Waiting on others"; a review queue that shows counts by status; deep links that open lists already filtered; a Current vs Last complete period switch.

Sources:
- https://help.dext.com/en/articles/775265-how-to-use-the-overview-page-in-a-business-account (17 Sep 2026; full page read)
- https://help.dext.com/en/articles/245212-how-to-use-the-overview-page-in-a-client-account (10 Feb 2026; full page read)
- https://help.dext.com/en/articles/622614-does-my-dext-practice-include-a-business-account (29 Jul 2026; search excerpt only)
- https://help.dext.com/en/articles/208300-the-costs-workspace (9 Mar 2026; search excerpt only)

---

## 6. UX guidance

**GOV.UK Design System**
- **Summary list / summary cards:** use these for key facts as key–value pairs. Summary cards group several summary lists about the same kind of thing and can carry card-level actions. Action links include visually hidden context (for example "Change<span hidden> name</span>"). Do not use them for tabular data or task lists. https://design-system.service.gov.uk/components/summary-list/ (checked 28 Oct 2026; full page read)
- **Task list:** shows each task's name with a status ("Completed", or a blue "Incomplete" tag) linked via `aria-describedby`. Use it only when users cannot finish in one sitting or need to choose the order. https://design-system.service.gov.uk/components/task-list/ (checked 28 Oct 2026; full page read)
- **Service navigation:** marks the active item with `aria-current` and a `<strong>` fallback, and collapses to a "Menu" toggle on small screens. https://design-system.service.gov.uk/components/service-navigation/ (checked 28 Oct 2026; full page read)
- **Navigate a service pattern:** navigation suits services that are "used repeatedly", "involve multiple tasks" and have no fixed order. "Navigation is not a site map and does not need to list every part of your service." Group external links after internal ones. Order elements from general to specific, and put an organisation switcher between the header and the service navigation. https://design-system.service.gov.uk/patterns/navigate-a-service/ (checked 28 Oct 2026; full page read)
- **Side navigation (MoJ Design System, status "to be reviewed", created June 2021):** use it for a **second level** of navigation and not for primary or global items. It supports **sections with headings**, and marks the active item with `aria-current="location"`. https://design-patterns.service.justice.gov.uk/components/side-navigation/ (checked 28 Oct 2026; full page read)

**Nielsen Norman Group**
- *Dashboards: Making Charts and Graphs Easier to Understand* (18 Jun 2017): a dashboard gives "at-a-glance information on which users can act quickly" and is "not intended" for exploration. Length and 2D position are the most accurately read preattentive cues, so **bar and line charts** work best. Avoid pie and donut charts, gauges, treemaps and 3D. Colour should not encode quantity, and should support shape or grouping rather than be the only cue (colour blindness affects about 8% of men). https://www.nngroup.com/articles/dashboards-preattentive/ (full page read)
- *Clutter-Free: One of the 3 Cs for Better Charts* (6 Feb 2022): Tufte's data-ink ratio and chartjunk. Direct data labels can make gridlines and axes unnecessary. https://www.nngroup.com/articles/clutter-charts/ (search excerpt only)
- *Menu-Design Checklist: 17 UX Guidelines* (7 Jun 2024). Relevant points:
  - show navigation on large screens
  - in applications, primary navigation goes on the left
  - always indicate the current location
  - use clear, familiar labels that are left-aligned and start with the key word
  - mark submenus with a caret
  - open submenus on **click, not hover**
  - avoid more than two cascading tiers
  - make targets large enough
  - avoid gimmicky patterns

  https://www.nngroup.com/articles/menu-design/ (full page read)
- *Local Navigation Is a Valuable Orientation and Wayfinding Aid* (4 Jul 2021): local navigation "should not be more salient than the global navigation… Visual hierarchy should reflect information hierarchy". Deep vertical trees push content aside through repeated indentation, so use breadcrumbs beyond 2–3 tiers. https://www.nngroup.com/articles/local-navigation/ (full page read)
- *Left-Side Vertical Navigation on Desktop* (16 May 2021): vertical navigation scales as the information architecture grows. Make it visually salient, label it in text rather than icons alone, and put less important items at the bottom. https://www.nngroup.com/articles/vertical-nav/ (search excerpt only)
- *Mobile Subnavigation* (16 Jul 2017): users must be able to find sub-navigation "with no chance of confusing it with the main navigation". Fewer than 6 subcategories suits an accordion; 6–15 suits a section menu; more than 15 needs a landing page. https://www.nngroup.com/articles/mobile-subnavigation/ (search excerpt only)

**Accessible charts**
- W3C WAI *Complex Images* tutorial: charts need a **two-part text alternative**, a short description (alt) plus a long description of values, trends and structure. You can use `<figure>`/`<figcaption>` with a data table, or `aria-describedby`. Make the long description available to everyone, and summarise the chart's message in the nearby text. https://www.w3.org/WAI/tutorials/images/complex/ (checked 28 Oct 2026; full page read)
- Government Analysis Function *Data visualisation: charts* (19 May 2022): WCAG 2.2 SC 1.1.1 requires every chart to have a text alternative "that serves the equivalent purpose", either a description or an accessible table. Do not put text inside chart images (SC 1.4.5). Use HTML or SVG rather than bitmaps. "If you cannot write down the message your chart is giving in a few sentences", rethink the chart. Use line charts for time series and bar charts for magnitude and ranking. https://analysisfunction.civilservice.gov.uk/policy-store/data-visualisation-charts/ (full page read)

---

## 7. What to copy (mapped to Accnomos cards)

- **AI summary (top, full width):** 2–4 sentences, followed by a "Based on:" line listing the figures and dates used. Each figure links to its source card. Precedent: QBO Feed (AI summary of recent transactions and the state of your finances) and Xero JAX ("showing its work").
- **Bank balances and cash flow:** for each account show balance, **last synced time** and **unreconciled count** (Xero shows reconciliation status beside the balance). Show cash flow as a 6-month bar chart of money in and out (Xero uses 6 months; FreeAgent offers 3, 6 or 12). Label it "bank transactions only, not profit", following FreeAgent's explanation.
- **Money in/out this month vs last:** two figures with the difference shown as an arrow, a signed amount and a percentage. Show the change in text and do not rely on colour alone. Use FreeAgent's period picker idea and Dext's **Current / Last complete** switch.
- **VAT / MTD deadlines:** a FreeAgent-style **tax timeline** with filters (Upcoming, Filed/Paid), the amount owed, and actions on each row (Review return, Submit, Mark paid). Add an "add to calendar" option. Like Sage Copilot's VAT assistant, warn as a deadline approaches.
- **Income Tax quarterly updates (MTD ITSA):** a GOV.UK-style task list per quarter (Records reviewed, Update submitted) with status tags. Show the next due date. Where an estimate uses last year's rates, say so, as FreeAgent does.
- **Review queue:** counts by status (To review, Ready, Processing), as Dext shows them, with deep links that open the list already filtered. Include "AI did this, please check" items, as QBO's Needs Attention does.
- **Unpaid invoices / bills (aged):** buckets for Current, 1–30, 31–60, 61–90 and 90+, with the **oldest overdue first** (Sage). Use a horizontal bar per bucket and label the value directly. Add one-click actions: Chase, and Add bill (Xero).
- **Payroll next run:** a summary card with pay date, employee count, estimated net pay and the RTI/FPS due date, plus a "Review run" action.
- **CIS:** a summary card with this month's deductions suffered and made, the CIS300 due date and a status tag.
- **Property income:** one row per property with rent received, expenses and net. Flag missing rent as a count with a link.
- **Spending insights:** top 5 categories compared with the same period last year (FreeAgent Insight), as a sorted bar chart.
- **Shopping list (personal):** a summary card with the item count and a link. Keep it out of the business view unless the user chooses to show it.
- **To-dos and month-end close:** split into **Needs your attention** and **Waiting on others** (Dext); strike through completed items (FreeAgent Radar). Show the month-end checklist as a task list with statuses.
- **Recent activity:** recent payments received (Xero) and recent submissions (Dext), 5–10 rows with a View all link.
- **Customisation:** show, hide and reorder cards; layout is per user (Xero); include a **privacy toggle** that masks figures (QBO). Make the default layout depend on the persona (business, sole trader, landlord, personal) and role, as Dext varies by role.
- **Answer-first headings:** name each card after the question it answers, as Xero does ("How much is owed to you?").

## 8. What to avoid

- Pie, donut, gauge, treemap and 3D charts, and colour as the only way of showing a value or status (NN/g).
- Charts without a text alternative. Every chart needs a one-line summary and a table or long description (W3C WAI, Analysis Function).
- Hover-only menus or tooltips, which QBO's sidebar relies on. Use click or tap and keyboard focus (NN/g #13).
- Cascading menus deeper than two tiers (NN/g #14).
- Hiding desktop navigation behind a hamburger menu (NN/g #1).
- Mixing cash and profit in one figure without saying so (FreeAgent spells out the difference).
- Showing estimated tax as if it were final. Label projections and say which year's rates were used (FreeAgent).
- Dashboards that become reporting pages. Dext: "entry point… not a full reporting page". NN/g: dashboards are not for exploration.
- Turning the home page into a sales pitch. Keep upsells such as Dext's "Discover features" below the fold, if they appear at all.
- Very small figures, low-contrast labels and cluttered gridlines (NN/g clutter and menu articles).
- Forcing a redesign on users with no way back. Xero and QBO both offered a temporary switch-back.

## 9. Navigation and sub-menus

Recommendation: a **left vertical sidebar** for the primary sections (NN/g: in applications, primary navigation goes on the left; vertical navigation scales). On mobile it collapses to a "Menu" button, as GOV.UK service navigation does. Use QBO's sidebar and Xero's grouping (Sales, Purchases, Reporting, Payroll, Accounting, Tax, Contacts) as a sanity check for the information architecture.

How sub-menu items must differ from main items. NN/g says local navigation should be visible but **less salient** than the global level, and "visual hierarchy should reflect information hierarchy".
- **Indentation:** indent second-level items one step (for example 12–16px further than the parent's text, or aligned under the parent label past the icon). Allow **one indentation level only**; for anything deeper, use a landing page or breadcrumbs (NN/g local navigation).
- **Smaller type:** about one step smaller than the main items (for example 14px against 16px), keeping line height and a tap target of at least 44px high (NN/g #11).
- **Lighter weight:** main items semibold, sub-items regular. Sub-items should use a softer text colour that still meets 4.5:1 contrast.
- **No icons on sub-items.** Icons appear only on top-level items and always with a text label (NN/g vertical navigation).
- **Section labels:** group long sub-menus under small uppercase or caption-style headings that are not links, as MoJ side navigation does with section headings. Mark them up as headings or `role="group"` with `aria-label`.
- **Expand/collapse:** a caret on parents that have children (NN/g #12), opened by click or tap and Enter/Space, with `aria-expanded`. Expanding should not navigate. Keep the current section expanded.
- **Active state:** a solid left bar (3–4px) and a tinted background on the active sub-item. The parent shows a quieter "contains active" state, for example bold text without the bar. Use `aria-current="page"` (GOV.UK and MoJ use `aria-current`). Never rely on colour alone.
- **Grouping:** use plain business labels by default, with an optional accountant label set, following Sage's Standard/Advanced navigation. Put less-used items (Settings, Help) at the bottom (NN/g vertical navigation). Keep a settings link at the end of each group, as Xero does.
- Order elements from general to specific: put the organisation or persona switcher (business, sole trader, landlord, personal) above the navigation, following the GOV.UK pattern.

## 10. AI summary rules

1. **Code supplies every figure.** A deterministic service builds a typed "facts" object (amounts in pence, dates, counts, deltas, rule-based flags) from the ledger. The model receives only that object.
2. **The AI only words the summary.** It picks the order and phrasing and must not calculate or estimate. The output is a template containing slots such as `{{fact:cash_total}}`, and the renderer fills them from the facts object, so the model cannot type a number itself.
3. **Validate before showing.** Reject any output with a digit or currency sign that did not come from a slot, any unknown slot ID, or text over the length limit. On rejection, fall back.
4. **Deterministic fallback.** A rule-based template summary, for example "You have £X across N accounts. N invoices are overdue (£Y). VAT return due DD Month." It shows when the model is unavailable, slow (time-box it to about 2s), or fails validation. The page must be complete without AI.
5. **Never invent numbers or dates.** If a fact is missing or stale (bank feed not synced, period not reconciled), say so, for example "Bank data last updated 3 days ago", and leave the figure out rather than guessing. FreeAgent's caveats about out-of-date accounts are the precedent.
6. **Show the workings.** Add a "Based on" disclosure listing the facts and their as-of times, with links to the source cards (precedent: Xero JAX "showing its work every step of the way").
7. **Projections are labelled as projections,** with their basis, for example "estimate using 2025/26 rates" (precedent: FreeAgent's Self Assessment projection note).
8. **No advice beyond the facts.** The summary may point to actions that already exist on the page (Review, Chase, Submit) and must not make tax decisions.
9. **Accessible and calm.** Plain UK English in 2–4 sentences. The summary must not be the only place a fact appears, because cards are the source of truth. Mark it as AI-generated.
10. **Log for audit:** keep the facts object, the prompt version, the output and whether the fallback was used.

Vendor precedent in short: QBO Feed's "AI-generated summary of recent transactions and the state of your finances"; QBO Needs Attention, which includes AI-completed work for review; Xero JAX's "Accountable Intelligence"; Sage Copilot's deadline alerts and checks; FreeAgent's Insights, which are rule-based and link to reports. None of the sources I read publishes how its summary is produced. The slot-filling approach above is our design, not a documented vendor method.
