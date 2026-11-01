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
