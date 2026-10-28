import { createBooksFolder, expect, signIn, test } from "./fixtures";

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
  await expect(tile("Needs attention")).toContainText("Nothing waiting");
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
  // The menu bar (src/components/TopBar.tsx): Review is Purchases › Bills (Review).
  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("button", { name: "Purchases", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Bills (Review)", exact: true })).toBeVisible();
});

test("setup checklist: signed in and incomplete, each row resumes its connect step; Dismiss is remembered", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/");
  const setup = page.getByRole("region", { name: "Get set up" });
  await expect(setup).toBeVisible();
  await expect(setup).toContainText(/\d of 7 done/);
  const row = (name: string) => setup.getByRole("link", { name: new RegExp(`^${name.replace(/[+()]/g, "\\$&")} — `) });
  await expect(row("Connect OneDrive")).toHaveAccessibleName("Connect OneDrive — review in Connect"); // signed in, so done
  await expect(row("Business name + VAT number")).toHaveAccessibleName("Business name + VAT number — set up in Connect");
  const links = {
    "Connect OneDrive": "/connect",
    "Choose your AI": "/connect/ai",
    "Business name + VAT number": "/connect/business",
    "VAT period": "/connect/business",
    "Invoice profile": "/settings#settings-invoice-profile",
    "Import Outlook contacts": "/settings#settings-intake",
    "Try a receipt": "/connect/ready",
  };
  for (const [name, href] of Object.entries(links)) await expect(row(name)).toHaveAttribute("href", href);
  await expect(row("Try a receipt")).toHaveAccessibleName("Try a receipt — try it in Connect"); // contains the visible "Try it"

  // A row resumes its wizard step.
  await row("VAT period").click();
  await expect(page).toHaveURL(/\/connect\/business$/);
  await expect(page.getByLabel("Business name")).toBeVisible();

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
