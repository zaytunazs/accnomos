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

test("signed out: P&L comparisons, section bars, aged links and the monthly table", async ({ page }) => {
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: /Profit and loss · Jul–Sep 2026/ })).toBeVisible();

  // This period vs the previous quarter and the same quarter last year, with change £ and %.
  const compare = page.getByRole("table", { name: /compared with earlier periods/ });
  await expect(compare).toBeVisible();
  await expect(compare.getByRole("columnheader", { name: "Apr–Jun 2026" })).toBeVisible();
  await expect(compare.getByRole("columnheader", { name: "Jul–Sep 2025" })).toBeVisible();
  await expect(compare.getByRole("row", { name: /^Sales/ })).toContainText("£31,900.00");
  await expect(compare.getByRole("row", { name: /^Net profit/ })).toContainText("+£1,484.00");
  await expect(compare.getByRole("row", { name: /^Net profit/ })).toContainText("+23.9%");
  // A small bar per section, with a text summary for screen readers.
  await expect(page.getByRole("img", { name: /^Sales: £31,900.00 this period/ })).toBeVisible();

  // Aged: a stacked bar per contact, and the name links to the contact.
  const debtors = page.getByRole("region", { name: "Debtors", exact: true });
  await expect(debtors.getByRole("img", { name: /Acme Kitchens Ltd:/ })).toBeVisible();
  const acme = debtors.getByRole("link", { name: "Acme Kitchens Ltd" });
  await expect(acme).toHaveAttribute("href", "/contacts?id=5a11c0ffee000001");
  await acme.click();
  await expect(page).toHaveURL(/\/contacts\?id=5a11c0ffee000001/);
  await expect(page.getByRole("main")).toContainText("Acme Kitchens Ltd");

  // Trend: the line chart plus its data table underneath.
  await page.goto("/reports");
  const monthly = page.getByRole("table", { name: /Sales, purchases and net per month/ });
  await expect(monthly.getByRole("row", { name: /Nov 2025/ })).toContainText("£7,200");
  await expect(monthly.getByRole("row", { name: /Sept 2026/ })).toContainText("£11,600");
});

test("signed in: P&L for a picked period from the ledger, exported to 07 Reports, nothing posted", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd, 14 Aug 2026: net £43.25, VAT £8.65, paid by card
  const events = (await runtime.files()).filter((f) => f.startsWith("_System/Ledger/events/"));

  await page.goto("/reports");
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Profit and loss · Oct–Dec 2026/ })).toBeVisible(); // the current period
  const current = page.getByRole("table", { name: "Profit and loss by account, Oct–Dec 2026" });
  await expect(current.getByRole("row", { name: /Net profit/ })).toContainText("£0.00");

  await pickVatPeriod(page, "Jul–Sep 2026");
  await expect(page.getByRole("heading", { name: /Profit and loss · Jul–Sep 2026/ })).toBeVisible();
  const pl = page.getByRole("table", { name: "Profit and loss by account, Jul–Sep 2026" });
  await expect(pl.getByRole("row", { name: /Total overheads/ })).toContainText("£43.25"); // ex VAT: VAT is not a cost
  await expect(pl.getByRole("row", { name: /Net loss/ })).toContainText("-£43.25");
  await expect(page.getByText("1 approved entry · calculated by code")).toBeVisible();

  // The comparisons come from two more runtime calls on the picked period's dates.
  const compare = page.getByRole("table", { name: /compared with earlier periods/ });
  await expect(compare.getByRole("row", { name: /^Overheads/ })).toContainText("+£43.25");
  await expect(compare.getByRole("row", { name: /^Overheads/ })).toContainText("(—)"); // no base to percent against

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
  const paper = page.getByRole("table", { name: /Profit and loss by account/ });
  await expect(paper.getByRole("row", { name: /Net profit/ })).toBeVisible();
  // Each report carries its own header on paper: period plus the code-calculated line.
  await expect(page.getByText("Calculated by code from approved entries.").first()).toBeVisible();
  await expect(page.getByText(/Profit and loss · Jul–Sep 2026/).first()).toBeVisible();
});
