import { createBooksFolder, expect, pickVatPeriod, signIn, test } from "./fixtures";

test("signed out: the labelled sample reports, no export", async ({ page }) => {
  await page.goto("/reports");
  await expect(page.getByRole("complementary", { name: "Sample data" })).toContainText("SAMPLE — FICTIONAL COMPANY");
  await expect(page.getByRole("heading", { name: /Profit and loss · Jul–Sep 2026/ })).toBeVisible();
  const pl = page.getByRole("table", { name: "Profit and loss by account, Jul–Sep 2026" });
  await expect(pl.getByRole("row", { name: /Gross profit/ })).toContainText("£15,920.00");
  await expect(pl.getByRole("row", { name: /Net profit/ })).toContainText("£7,705.00");
  await expect(page.getByText(/^As approved:/)).toBeVisible();
  await expect(page.getByRole("img", { name: /Sales, purchases and net per month, Nov 2025 to Oct 2026/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Debtors", exact: true })).toContainText("Acme Kitchens Ltd");
  await expect(page.getByRole("heading", { name: "VAT by period" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export to OneDrive" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Reports" })).toHaveAttribute("aria-current", "page");
});

test("signed in: P&L for a picked period from the ledger, exported to 07 Reports, nothing posted", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd, 14 Aug 2026: net £43.25, VAT £8.65, paid by card
  const events = (await runtime.files()).filter((f) => f.startsWith("_System/Ledger/events/"));

  await page.goto("/reports");
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Profit and loss · Oct–Dec 2026/ })).toBeVisible(); // the current period
  await expect(page.getByRole("row", { name: /Net profit/ })).toContainText("£0.00");

  await pickVatPeriod(page, "Jul–Sep 2026");
  await expect(page.getByRole("heading", { name: /Profit and loss · Jul–Sep 2026/ })).toBeVisible();
  const pl = page.getByRole("table", { name: "Profit and loss by account, Jul–Sep 2026" });
  await expect(pl.getByRole("row", { name: /Total overheads/ })).toContainText("£43.25"); // ex VAT: VAT is not a cost
  await expect(pl.getByRole("row", { name: /Net loss/ })).toContainText("-£43.25");
  await expect(page.getByText("1 approved entry · calculated by code")).toBeVisible();

  await page.getByRole("button", { name: "Export to OneDrive" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved to" })).toContainText(
    "Saved to 07 Reports/2026-10-27-reports.xlsx in your OneDrive (P&L, Debtors, Creditors, VAT summary, Trend).",
  );
  const files = await runtime.files();
  expect(files).toContain("07 Reports/2026-10-27-reports.xlsx");
  expect(files.filter((f) => f.startsWith("_System/Ledger/events/"))).toEqual(events);
});

test("print: the reports print without chrome or controls", async ({ page }) => {
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: /Profit and loss/ })).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Print" })).toBeHidden();
  await expect(page.getByRole("complementary", { name: "Sample data" })).toBeHidden();
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY · fictional figures")).toBeVisible(); // the paper's own label
  await expect(page.getByRole("row", { name: /Net profit/ })).toBeVisible();
});
