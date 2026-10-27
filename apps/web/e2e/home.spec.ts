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

  await expect(page.getByRole("region", { name: "Recent activity" })).toContainText("Posted Novex Office Supplies Ltd £51.90 to the ledger");

  // Signed in: no "Not connected yet?" banner or pitch, and no made-up count on the Review link.
  await expect(page.getByText("Not connected yet?")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "See the demo books" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Review", exact: true })).toBeVisible();
});

test("Review badge counts the proposals waiting", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.dropInInbox();
  await page.goto("/review");
  await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
  await expect(page.getByRole("status")).toHaveText("1 new proposal");

  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Review 1 item to review" })).toBeVisible();
});

test("signed out: the pitch, the connect banner and the sample books", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "See the demo books" })).toBeVisible();
  await expect(page.getByText("Not connected yet?")).toBeVisible();
});
