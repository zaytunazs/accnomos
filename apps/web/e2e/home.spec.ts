import { confirmScan, createBooksFolder, expect, signIn, test } from "./fixtures";

test("Home dashboard: tiles, deadlines and activity from the books, no signed-out pitch", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd, 14 Aug 2026, paid by card: £8.65 VAT to reclaim for Jul–Sep

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Good morning, Sam" })).toBeVisible();

  const tile = (label: string | RegExp) => page.getByRole("group", { name: label });
  await expect(tile("VAT estimate · Jul–Sep 2026")).toContainText("£9");
  await expect(tile("VAT estimate · Jul–Sep 2026").getByRole("link")).toHaveText("To reclaim, return due 7 Nov");
  await expect(tile("Owed by you")).toContainText("Nothing unpaid"); // paid by card
  await expect(tile("Owed to you")).toContainText("£0");
  // What needs attention: up to four tiles under the summary, each one link to where it is cleared. Calm when empty.
  const attention = page.getByRole("region", { name: "What needs attention" });
  await expect(attention.getByRole("link")).toHaveCount(4);
  const link = (label: string) => attention.getByRole("link", { name: new RegExp(`^${label}`) });
  await expect(link("Items to review")).toContainText("Nothing to review");
  await expect(link("Items to review")).toHaveAttribute("href", "/review");
  await expect(link("Overdue invoices")).toContainText("None overdue");
  await expect(link("Overdue invoices")).toHaveAttribute("href", "/invoices");
  await expect(link("Bank lines to reconcile")).toContainText("All matched");
  await expect(link("Bank lines to reconcile")).toHaveAttribute("href", "/bank/reconcile");
  await expect(link("Next deadline")).toContainText("VAT return Jul–Sep 2026, 7 Nov");
  await expect(link("Next deadline")).toHaveAttribute("href", "/vat");
  await expect(tile("Cash in bank").getByRole("link")).toHaveText("Import a statement and match a line");

  const deadlines = page.getByRole("region", { name: "Deadlines" });
  await expect(deadlines).toContainText("7 NOV: VAT return Jul–Sep 2026 due");
  await expect(deadlines).toContainText("11 days left");
  await expect(deadlines).toContainText("£8.65 to reclaim (estimated)");
  await expect(deadlines).toContainText("31 DEC: VAT period Oct–Dec 2026 ends");
  // No business settings saved: the runtime assumed stagger 1 and the tile says so.
  await expect(deadlines).toContainText("Assuming Mar/Jun/Sep/Dec quarters — set yours in Settings");

  await expect(page.getByRole("region", { name: "Recent activity" })).toContainText("Posted Novex Office Supplies Ltd £51.90 to the ledger");

  // Signed in: no "Not connected yet?" banner or pitch, and no made-up count on the Review link.
  await expect(page.getByText("Not connected yet?")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "See the demo books" })).toHaveCount(0);
  // The menu bar (src/components/TopBar.tsx): Home · Review · Bank are plain links, in that order; Review is also Purchases › Bills (Review).
  const nav = page.getByRole("navigation", { name: "Main" });
  const top = nav.locator(":scope > ul > li > a, :scope > ul > li > button");
  await expect(top).toContainText(["Home", "Review", "Bank", "Sales", "Purchases", "Reporting", "Tax", "More"]);
  await expect(nav.getByRole("link", { name: "Review", exact: true })).toHaveAttribute("href", "/review");
  await expect(nav.getByRole("link", { name: "Bank", exact: true })).toHaveAttribute("href", "/bank");
  await nav.getByRole("button", { name: "More", exact: true }).click();
  for (const name of ["Reconcile", "Chart of accounts", "All contacts"]) await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
  await nav.getByRole("button", { name: "More", exact: true }).click();
  await nav.getByRole("button", { name: "Purchases", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Bills (Review)", exact: true })).toBeVisible();
});

test("setup checklist: signed in and incomplete, each row resumes its connect step; Dismiss is remembered", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/");
  const setup = page.getByRole("region", { name: "Get set up" });
  await expect(setup).toBeVisible();
  await expect(setup).toContainText(/\d of 8 done/);
  const row = (name: string) => setup.getByRole("link", { name: new RegExp(`^${name.replace(/[+()]/g, "\\$&")} — `) });
  await expect(row("Connect OneDrive")).toHaveAccessibleName("Connect OneDrive — review in Connect"); // signed in, so done
  await expect(row("Business name + VAT number")).toHaveAccessibleName("Business name + VAT number — set up in Connect");
  const links = {
    "Connect OneDrive": "/connect",
    "Choose your AI": "/connect/ai",
    "Business name + VAT number": "/connect/business",
    "VAT period": "/connect/business",
    "Business details wizard": "/setup",
    "Invoice profile": "/settings#settings-invoice-profile",
    "Import Outlook contacts": "/settings#settings-intake",
    "Try a receipt": "/connect/ready",
  };
  for (const [name, href] of Object.entries(links)) await expect(row(name)).toHaveAttribute("href", href);
  await expect(row("Business details wizard")).toHaveAccessibleName("Business details wizard — set up in Review");
  await expect(row("Try a receipt")).toHaveAccessibleName("Try a receipt — try it in Connect"); // contains the visible "Try it"

  // A row resumes its wizard step.
  await row("VAT period").click();
  await expect(page).toHaveURL(/\/connect\/business$/);
  await expect(page.getByLabel("Business name")).toBeVisible();

  // The wizard row resumes in the set-up wizard.
  await page.goto("/");
  await row("Business details wizard").click();
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole("heading", { level: 1, name: "Set up your business" })).toBeVisible();

  await page.goto("/");
  await setup.getByRole("button", { name: "Dismiss" }).click();
  await expect(setup).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Good morning, Sam" })).toBeVisible();
  await expect(setup).toHaveCount(0);
});

test("setup checklist: never shown signed out", async ({ page }) => {
  await page.goto("/try");
  await expect(page.getByRole("link", { name: "See the demo books" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Get set up" })).toHaveCount(0);
});

test("Review badge counts the proposals waiting", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.dropInInbox();
  await page.goto("/review");
  await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
  await confirmScan(page);
  await expect(page.getByRole("status")).toHaveText("1 new proposal");

  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(page.getByRole("link", { name: "Notifications: 1 item to review" })).toBeVisible();
  await nav.getByRole("button", { name: /^Purchases\s*, 1 to review$/ }).click();
  await expect(nav.getByRole("link", { name: "Bills (Review) 1 item to review" })).toBeVisible();
});

test("signed out: the pitch, the connect banner and the sample books (on /try; / is the landing page)", async ({ page }) => {
  await page.goto("/try");
  await expect(page.getByRole("link", { name: "See the demo books" })).toBeVisible();
  await expect(page.getByText("Not connected yet?")).toBeVisible();
});

test("Home deadlines: a VAT stagger saved in Settings is used and nothing is called an assumption", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();
  await page.addInitScript(() => {
    window.localStorage.setItem("accnomos.business", JSON.stringify({ vatPeriod: "quarterly", stagger: "2" }));
  });

  await page.goto("/");
  const deadlines = page.getByRole("region", { name: "Deadlines" });
  await expect(deadlines).toContainText("VAT period"); // loaded
  await expect(deadlines).not.toContainText("Assuming");
});

test("sample books (/try): the four attention tiles link to Review, Invoices, Reconcile and the next deadline", async ({ page }) => {
  await page.goto("/try");
  const attention = page.getByRole("region", { name: "What needs attention" });
  await expect(attention.getByRole("link")).toHaveCount(4);
  const hrefs = await attention.getByRole("link").evaluateAll((as) => as.map((a) => [a.textContent, a.getAttribute("href")]));
  expect(hrefs.map(([, h]) => h)).toEqual(["/review", "/invoices", "/bank/reconcile", "/payroll"]);
  await expect(attention.getByRole("link", { name: /^Items to review/ })).toContainText("3 to approve");
  await expect(attention.getByRole("link", { name: /^Bank lines to reconcile/ })).toContainText("2 lines to match");
  await expect(attention.getByRole("link", { name: /^Next deadline/ })).toContainText("Pay run 2026-10 to confirm");
  // Today comes next, and the Income Tax, Payroll, CIS and Property cards sit below Month-end.
  const order = await page.evaluate(() => {
    const y = (n: string) => document.querySelector(`[aria-label="${n}"]`)?.getBoundingClientRect().top ?? -1;
    return [y("What needs attention"), y("Today")];
  });
  expect(order[0]).toBeGreaterThan(0);
  expect(order[1]).toBeGreaterThan(order[0]);
});

test("Business snapshot (signed in): the year to date, the last 12 months and the cash line from the books", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex, 14 Aug 2026: £43.25 office costs, £8.65 VAT to reclaim; no bank statement yet

  await page.goto("/");
  const snap = page.getByRole("region", { name: "Business snapshot" });
  const figure = (label: string) => snap.getByRole("group", { name: label });
  // No profile saved: a company, so the year runs from 1 January (services/runtime/app/home_overview.py `year_start`).
  await expect(snap).toContainText("1 Jan – 27 Oct 2026 against 1 Jan – 27 Oct 2025 · accrual from approved entries");
  await expect(figure("Turnover")).toContainText("£0");
  await expect(figure("Turnover")).toContainText("— no figure last year"); // nothing last year: no percentage
  await expect(figure("Expenses")).toContainText("£43");
  await expect(figure("Net loss")).toContainText("£43");
  await expect(figure("VAT to reclaim")).toContainText("£9");
  await expect(figure("VAT to reclaim")).toContainText("Jul–Sep 2026 · due 7 Nov");
  await expect(snap.getByRole("link", { name: "Profit and loss" })).toHaveAttribute("href", "/reports");
  await expect(snap.getByRole("link", { name: "VAT return" })).toHaveAttribute("href", "/vat");

  // The chart (under Trend and cash, after Goals & progress): one image with a text alternative, the figures as a
  // table, and the arrow keys read each month.
  const trend = page.getByRole("region", { name: "Trend and cash" });
  const chart = trend.getByRole("img", { name: /^Sales and purchases as bars/ });
  await expect(chart).toBeVisible();
  await expect(chart).toHaveAttribute("aria-label", /Nov 2025 to Oct 2026/);
  await expect(trend.getByRole("table", { name: "Sales, purchases and net profit per month" })).toContainText("Aug 2026£0£43-£43");
  const readout = trend.locator("[data-chart-readout]");
  await expect(readout).toHaveText("Oct 2026: sales £0 · purchases £0 · net £0");
  await chart.focus();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(readout).toHaveText("Aug 2026: sales £0 · purchases £43 · net -£43");
  await expect(trend.getByRole("link", { name: "Full trend" })).toHaveAttribute("href", "/reports");

  // No bank statement: a calm empty state, never a made-up line.
  await expect(trend.getByRole("region", { name: "Cash, next 90 days" })).toContainText("Import a bank statement to see cash forecast");
  await expect(trend.getByRole("link", { name: "Cash flow forecast" })).toHaveAttribute("href", "/reports/cashflow");

  // Top to bottom: What needs attention, the year to date, Goals & progress, the charts, then Today.
  const order = await page.evaluate(() =>
    ["What needs attention", "business-snapshot", "home-goals-title", "business-trend", "Today"].map((n) => {
      const el = document.querySelector(`[aria-label="${n}"]`) ?? document.getElementById(n);
      return el?.getBoundingClientRect().top ?? -1;
    }),
  );
  expect(order.every((y) => y !== -1), `found ${order.join(", ")}`).toBe(true);
  for (let i = 1; i < order.length; i++) expect(order[i], `order ${order.join(" < ")}`).toBeGreaterThan(order[i - 1]);
});

test("Business snapshot (/try): the sample year, chart and cash line, marked as sample", async ({ page }) => {
  await page.goto("/try");
  const snap = page.getByRole("region", { name: /^Business snapshot ?Sample$/ });
  const figure = (label: string) => snap.getByRole("group", { name: label });
  await expect(figure("Turnover")).toContainText("£148,620");
  await expect(figure("Turnover")).toContainText("▲ up 12% vs last year");
  await expect(figure("Expenses")).toContainText("▲ up 8% vs last year");
  await expect(figure("Net profit")).toContainText("£47,280");
  await expect(figure("Net profit")).toContainText("22% vs last year");
  await expect(figure("Net profit")).toContainText("Last year £38,600");
  await expect(figure("VAT to pay")).toContainText("£2,140");
  await expect(figure("VAT to pay")).toContainText("due 7 Nov");
  const trend = page.getByRole("region", { name: /^Trend and cash ?Sample$/ });
  await expect(trend.getByRole("img", { name: /^Sales and purchases as bars/ })).toBeVisible();
  await expect(trend.getByRole("table", { name: "Sales, purchases and net profit per month" }).getByRole("row")).toHaveCount(13);
  const cash = trend.getByRole("region", { name: "Cash, next 90 days" });
  await expect(cash.getByRole("img", { name: /^Forecast bank balance/ })).toBeVisible();
  await expect(cash).toContainText("Lowest £1,240 on 14 Dec");
  await expect(cash).toContainText("Today £12,480");
  for (const [name, href] of [["Profit and loss", "/reports"], ["VAT return", "/vat"]]) {
    await expect(snap.getByRole("link", { name, exact: true })).toHaveAttribute("href", href);
  }
  for (const [name, href] of [["Full trend", "/reports"], ["Cash flow forecast", "/reports/cashflow"]]) {
    await expect(trend.getByRole("link", { name, exact: true })).toHaveAttribute("href", href);
  }
  await expect(snap).toContainText("Sample figures from the fictional Bramblewood books");
  await expect(trend).toContainText("Sample figures from the fictional Bramblewood books");
});
