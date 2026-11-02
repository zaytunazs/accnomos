import type { Page } from "@playwright/test";
import { createBooksFolder, expect, settingsTab, signIn, test, type Runtime } from "./fixtures";

/**
 * Personal books get their own treatment, as each business kind does (lib/nav.ts HOUSEHOLD_GROUPS): a household menu
 * (Home · Review · Bank · Budget · Spending · Goals · More), household phone tabs (Home · Review · Budget · Goals · Ask),
 * household set-up steps, and Settings without the business-only sections. A business's menu is unchanged.
 */

const PERSONAL = { name: "Sam at home", kind: "personal", settings: {} };
const COMPANY = { name: "Sam Builds Ltd", kind: "company", settings: { company_number: "01234567", vat_registered: true } };

async function open(page: Page, runtime: Runtime, profile: Record<string, unknown>) {
  await runtime.api("PUT", "/profile", profile);
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
}

test("personal books: the household menu, Budget without a switch, household set-up steps and Settings", async ({ page, runtime }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, runtime, PERSONAL);
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const link of ["Home", "Review", "Bank", "Budget", "Goals"]) await expect(nav.getByRole("link", { name: link, exact: true })).toBeVisible();
  for (const gone of ["Sales", "Purchases", "Reporting", "Tax"]) await expect(nav.getByRole("button", { name: gone, exact: true })).toHaveCount(0);
  await nav.getByRole("button", { name: "Spending", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Spending overview" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Shopping list" })).toBeVisible();
  await nav.getByRole("button", { name: "Spending", exact: true }).click();
  await nav.getByRole("button", { name: "More", exact: true }).click();
  for (const link of ["Bank rules", "Short-term cash flow", "Documents", "Audit trail"]) await expect(nav.getByRole("link", { name: link, exact: true })).toBeVisible();
  for (const gone of ["Chart of accounts", "Manual journals", "Pay runs", "VAT returns", "Profit and loss", "Vehicles and mileage"])
    await expect(nav.getByRole("link", { name: gone, exact: true })).toHaveCount(0);
  await nav.getByRole("button", { name: "More", exact: true }).click();

  // Set-up asks household questions, ticked from the books; no business name, VAT or invoice steps.
  const setup = page.getByRole("region", { name: "Get set up" });
  for (const step of ["Import a bank statement", "Set your monthly budgets", "Set a goal", "Choose your AI"]) await expect(setup).toContainText(step);
  for (const gone of ["Business name + VAT number", "VAT period", "Invoice profile", "Business details wizard"]) await expect(setup).not.toContainText(gone);
  await expect(setup.getByRole("link", { name: "Set your monthly budgets — set up in Budget" })).toHaveAttribute("href", "/personal");

  // Budget is the household overview, on without the business's "Show personal finances" switch.
  await nav.getByRole("link", { name: "Budget", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Budget" })).toBeVisible();
  await expect(page.getByText("Personal finances are off.")).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Budget", exact: true })).toHaveAttribute("aria-current", "page");

  // Settings: a Profile tab, without the business-only sections.
  await page.goto("/settings");
  const profile = await settingsTab(page, "Profile");
  await expect(profile.getByRole("heading", { name: "Set-up wizard" })).toBeVisible();
  for (const gone of ["VAT periods", "Staff", "On your invoices", "Personal finances"])
    await expect(profile.getByRole("heading", { name: gone, exact: true })).toHaveCount(0);
});

test("personal books on a phone: Home · Review · Budget · Goals · Ask, no VAT tab", async ({ page, runtime }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, runtime, PERSONAL);
  const tabs = page.getByRole("navigation", { name: "Sections" });
  await expect(tabs.getByRole("link", { name: "Budget" })).toBeVisible();
  await expect(tabs.getByRole("link")).toHaveText([/Home/, /Review/, "Budget", "Goals", "Ask"]);
  await tabs.getByRole("link", { name: "Goals" }).click();
  await expect(page).toHaveURL(/\/goals$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("a company keeps the business menu and tabs", async ({ page, runtime }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, runtime, COMPANY);
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const group of ["Sales", "Purchases", "Reporting", "Tax"]) await expect(nav.getByRole("button", { name: group, exact: true })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Budget", exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("navigation", { name: "Sections" }).getByRole("link", { name: "VAT" })).toBeVisible();
});
