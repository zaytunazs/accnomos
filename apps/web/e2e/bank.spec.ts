import { join } from "node:path";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// SAMPLE — FICTIONAL COMPANY: six lines, three paying seeded entries exactly, one a penny out, a transfer and a fee.
const BARCLAYS = join(__dirname, "../../../evals/gold/bank/barclays.csv");

test("upload the gold Barclays CSV → confirm a match → settle the unmatched lines", async ({ page, runtime }) => {
  await runtime.reset("bank"); // Screwfix, Acme Kitchens, Toolstation and Travis Perkins in the ledger
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");
  expect((await runtime.files()).some((f) => f.startsWith("04 Bank statements/") && f.endsWith(".csv"))).toBeTruthy();

  // Statement view: the canonical folder path, per-line status and the running balance from the CSV.
  const statement = page.getByRole("button", { name: /04 Bank statements\/.*barclays\.csv/ });
  await expect(statement).toBeVisible();
  await statement.click();
  const statementLines = page.getByRole("region", { name: /Lines in .*barclays\.csv/ });
  await expect(statementLines.getByText("TO SAVINGS 40-11-22 87654321 TFR")).toBeVisible();
  await expect(statementLines.getByText(/^Balance /).first()).toBeVisible();
  await statementLines.getByLabel("Show").selectOption("unmatched");
  await expect(statementLines.getByText("TO SAVINGS 40-11-22 87654321 TFR")).toBeVisible();
  await expect(statementLines.getByText("SCREWFIX DIRECT ON 30 SEP CLP")).toHaveCount(0);
  await statementLines.getByLabel("Show").selectOption("all");

  const lines = page.getByRole("region", { name: "Bank lines" });
  const tab = (name: string) => lines.getByRole("tab", { name: new RegExp(`^${name}`) });
  await expect(tab("Matches")).toContainText("4"); // three exact, Travis Perkins a penny out
  await expect(tab("Unmatched")).toContainText("2");
  // The penny-out suggestion stays per row and out of the bulk confirm, with its reason shown.
  await expect(lines.getByRole("button", { name: "Confirm all 3 exact matches" })).toBeVisible();
  await expect(lines.getByRole("table").getByText("1p out")).toBeVisible();

  await lines.getByRole("table").getByRole("button", { name: /^Confirm match: SCREWFIX DIRECT/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Matched" })).toHaveText("Matched SCREWFIX DIRECT ON 30 SEP CLP to Screwfix.");
  await expect(tab("Matches")).toContainText("3");

  // The reconciled tile explains what counts as decided.
  await page.getByRole("button", { name: "What counts?" }).click();
  await expect(page.getByText("Suggested matches do not count until you confirm them.")).toBeVisible();

  await tab("Unmatched").click();
  const transfer = lines.getByRole("listitem").filter({ hasText: "TO SAVINGS" });
  await transfer.getByRole("button", { name: /^Actions for TO SAVINGS/ }).click();
  await transfer.getByRole("menuitem", { name: /^Mark as transfer/ }).click();
  const transferSheet = page.getByRole("dialog");
  await expect(transferSheet).toContainText("TO SAVINGS 40-11-22 87654321 TFR will be marked as a transfer between your own accounts. Nothing will be booked.");
  await transferSheet.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "transfer" })).toHaveText("TO SAVINGS 40-11-22 87654321 TFR marked as a transfer.");
  await expect(tab("Unmatched")).toContainText("1"); // the line moved tabs without a reload

  const fee = lines.getByRole("listitem").filter({ hasText: "BUSINESS ACCOUNT FEE" });
  await fee.getByRole("button", { name: /^Actions for BUSINESS ACCOUNT FEE/ }).click();
  await fee.getByRole("menuitem", { name: "Create expense proposal" }).click();
  const feeSheet = page.getByRole("dialog");
  await expect(feeSheet).toContainText("A £6.50 expense proposal with no VAT reclaimed will wait in Review.");
  await feeSheet.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Expense proposal" })).toHaveText("Expense proposal for BUSINESS ACCOUNT FEE is waiting on Review.");
  await expect(fee.getByRole("button", { name: "Proposal created" })).toBeDisabled(); // nothing posted until approved
  await expect(fee.getByRole("link", { name: "Approve it on Review" })).toBeVisible();

  // Changes offer a rebuild of Books.xlsx.
  await expect(page.getByRole("button", { name: "Rebuild Books.xlsx" })).toBeVisible();

  await tab("Done").click();
  const done = lines.getByRole("tabpanel");
  await expect(done.getByRole("row").filter({ hasText: "SCREWFIX" })).toContainText("Matched");
  await expect(done.getByRole("row").filter({ hasText: "TO SAVINGS" })).toContainText("Transfer");
});

test.describe("390 px wide", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("stacked cards, no sideways scroll, action menu and sheet reachable, live results", async ({ page, runtime }) => {
    await runtime.reset("bank");
    await signIn(page);
    await createBooksFolder(page);

    await page.goto("/bank");
    await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
    await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");

    const lines = page.getByRole("region", { name: "Bank lines" });
    // Matches render as cards (no table), with a per-row Confirm.
    await expect(lines.getByRole("table")).toHaveCount(0);
    await expect(lines.getByRole("button", { name: /^Confirm match: SCREWFIX/ }).first()).toBeVisible();

    const checkWidth = async () => {
      const { scroll, width, offscreen } = await page.evaluate(() => {
        const inScroller = (el: Element) => {
          for (let p = el.parentElement; p; p = p.parentElement) {
            if (["auto", "scroll"].includes(getComputedStyle(p).overflowX)) return true;
          }
          return false;
        };
        const offscreen = [...document.querySelectorAll("button, [role=tab], a[class*='rounded-xl']")]
          .filter((el) => el.checkVisibility() && !inScroller(el))
          .filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && (r.left < -1 || r.right > window.innerWidth + 1);
          })
          .map((el) => (el.textContent ?? "").trim().slice(0, 40));
        return { scroll: document.documentElement.scrollWidth, width: window.innerWidth, offscreen };
      });
      expect(width).toBe(390);
      expect(scroll).toBeLessThanOrEqual(width);
      expect(offscreen).toEqual([]);
    };
    await checkWidth();

    // Statement view opens inline and still fits.
    await page.getByRole("button", { name: /04 Bank statements\/.*barclays\.csv/ }).click();
    await expect(page.getByRole("region", { name: /Lines in .*barclays\.csv/ })).toBeVisible();
    await checkWidth();

    // Results are announced.
    await expect(lines.getByRole("tabpanel")).toHaveAttribute("aria-live", "polite");

    // Unmatched action menu and confirm sheet are reachable.
    await lines.getByRole("tab", { name: /^Unmatched/ }).click();
    const transfer = lines.getByRole("listitem").filter({ hasText: "TO SAVINGS" });
    await transfer.getByRole("button", { name: /^Actions for TO SAVINGS/ }).click();
    const item = transfer.getByRole("menuitem", { name: /^Mark as transfer/ });
    await expect(item).toBeInViewport();
    await item.click();
    const sheet = page.getByRole("dialog");
    await expect(sheet).toBeInViewport();
    await expect(sheet).toContainText("Nothing will be booked.");
    await sheet.getByRole("button", { name: "Cancel" }).click();
    await checkWidth();
  });
});

test("Enter on a focused match row confirms it", async ({ page, runtime }) => {
  await runtime.reset("bank"); // Screwfix, Acme Kitchens, Toolstation and Travis Perkins in the ledger
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  const lines = page.getByRole("region", { name: "Bank lines" });
  const tab = (name: string) => lines.getByRole("tab", { name: new RegExp(`^${name}`) });
  await expect(tab("Matches")).toContainText("4");

  await lines.getByRole("table").getByRole("row", { name: /ACME KITCHENS/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Matched" })).toContainText("Matched ACME KITCHENS LTD INV-0042 BGC");
  await expect(tab("Matches")).toContainText("3");
});
