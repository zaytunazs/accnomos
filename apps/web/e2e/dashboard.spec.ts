import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test, type Runtime } from "./fixtures";

/**
 * Home as a dashboard (src/components/home/OverviewCards.tsx, GET /books/home): the checked summary at the top, then
 * one card per thing that matters, each linking to its page and hidden when these books do not use that feature.
 * Also the menu hierarchy (src/components/TopBar.tsx): sub-menus look lower than the main menu.
 */

/** A Home card by its heading; on the sample books the heading also carries a "Sample" pill. */
const card = (page: Page, name: string) =>
  page.getByRole("region", { name: new RegExp(`^${name.replace(/[()]/g, "\\$&")}( ?Sample)?$`) });

async function home(page: Page, runtime: Runtime, profile?: Record<string, unknown>) {
  if (profile) await runtime.api("PUT", "/profile", profile);
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
  await expect(card(page, "Your summary").locator("[data-home-summary]")).toBeVisible();
}

const COMPANY = { name: "Sam Builds Ltd", kind: "company", settings: { company_number: "01234567", vat_registered: true } };
const SOLE_TRADER = { name: "Sam Builds", kind: "sole_trader", settings: { vat_registered: false } };
const PERSONAL = { name: "Sam at home", kind: "personal", settings: {} };

test("business: the AI summary on top, then money, aged debts and deadlines, each linking to its page", async ({ page, runtime }) => {
  await home(page, runtime, COMPANY);
  const summary = card(page, "Your summary");
  // Test mode: the stub AI words it, quoting only the facts it was given; code checked the numbers.
  await expect(summary).toContainText("Test stub summary: no bank balance yet. 0 waiting in Review.");
  await expect(summary).toContainText("worded by your AI (accnomos-test-stub), numbers checked by code");

  const money = card(page, "Money in and out");
  await expect(money.getByRole("table")).toContainText("October 2026 so far");
  await expect(money.getByRole("table")).toContainText("September 2026");
  await expect(money.getByRole("link", { name: "Open cash flow" })).toHaveAttribute("href", "/reports/cashflow");

  await expect(card(page, "Unpaid invoices and bills").getByRole("link", { name: "Open aged report" })).toHaveAttribute(
    "href",
    "/reports#aged-heading",
  );
  const coming = card(page, "Coming up");
  await expect(coming.getByRole("link", { name: "VAT return Jul–Sep 2026" })).toHaveAttribute("href", "/vat");
  await expect(coming).toContainText("7 Nov · in 11 days");

  // Not used by this company: no Income Tax, payroll, CIS or property cards.
  for (const name of ["Income Tax (MTD)", "Payroll", "CIS (construction)", "Property income"]) await expect(card(page, name)).toHaveCount(0);
  // The cards that were already there still are.
  for (const name of ["Today", "Needs attention", "Spending", "To-dos", "Month-end"]) await expect(card(page, name)).toBeVisible();
});

test("sole trader: Income Tax quarterly update and Self Assessment, no VAT", async ({ page, runtime }) => {
  await home(page, runtime, SOLE_TRADER);
  const tax = card(page, "Income Tax (MTD)");
  await expect(tax).toContainText("7 Nov");
  await expect(tax).toContainText("Quarterly update to 5 Oct (2026-27) due in 11 days");
  await expect(tax).toContainText("Self Assessment return and payment due 31 Jan 2027");
  await expect(tax.getByRole("link", { name: "Open quarterly updates" })).toHaveAttribute("href", "/self-employment");
  const coming = card(page, "Coming up");
  await expect(coming).not.toContainText("VAT return");
  await expect(card(page, "Unpaid invoices and bills")).toBeVisible();
});

test("landlord: a registered property shows property income and the Income Tax card", async ({ page, runtime }) => {
  await runtime.api("PUT", "/profile", PERSONAL);
  await runtime.api("POST", "/property/properties", { name: "Flat 1", postcode: "LS1 1AA" });
  await home(page, runtime);
  const property = card(page, "Property income");
  await expect(property).toContainText("Profit in 2026-27 so far: £0 rent, £0 costs · 1 property");
  await expect(property.getByRole("link", { name: "Open property" })).toHaveAttribute("href", "/property");
  await expect(card(page, "Income Tax (MTD)")).toContainText("due in 11 days");
});

test("personal books: no business cards (aged debts, payroll, CIS, VAT, Income Tax)", async ({ page, runtime }) => {
  await home(page, runtime, PERSONAL);
  await expect(card(page, "Money in and out")).toBeVisible();
  for (const name of ["Unpaid invoices and bills", "Income Tax (MTD)", "Payroll", "CIS (construction)", "Property income"]) {
    await expect(card(page, name)).toHaveCount(0);
  }
  await expect(card(page, "Your summary")).not.toContainText("VAT");
});

test("signed out (/try): the sample summary and cards are marked as sample", async ({ page }) => {
  await page.goto("/try");
  const summary = card(page, "Your summary");
  await expect(summary).toContainText("You had £12,480.00 in the bank on 24 Oct 2026.");
  await expect(summary).toContainText("Sample");
  await expect(card(page, "Payroll")).toContainText("The 2026-10 pay run is prepared and waits for you");
  // The chart has its figures as a table: a text alternative for the bars, which are hidden from screen readers.
  const money = card(page, "Money in and out");
  await expect(money.getByRole("table")).toContainText("£18,420");
  await expect(money.locator("[aria-hidden=true] span").first()).toBeAttached();
});

/** font size, weight and left edge of an element. */
const metrics = (el: import("@playwright/test").Locator) =>
  el.evaluate((n) => {
    const s = getComputedStyle(n);
    return { size: parseFloat(s.fontSize), weight: Number(s.fontWeight), left: n.getBoundingClientRect().left };
  });

test("menu hierarchy: sub-menu links are indented, smaller and lighter than the main menu, under a section label", async ({
  page,
}) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/invoices");
  const nav = page.getByRole("navigation", { name: "Main" });
  const sales = nav.getByRole("button", { name: "Sales" });
  await sales.click();
  const sub = nav.locator("[data-submenu]").filter({ visible: true });
  const item = sub.getByRole("link", { name: "Quotes" });
  const top = await metrics(sales);
  const second = await metrics(item);
  expect(second.size).toBeLessThan(top.size);
  expect(second.weight).toBeLessThan(top.weight);
  const label = nav.getByText("Sales", { exact: true }).filter({ visible: true }).last();
  expect((await metrics(item)).left).toBeGreaterThan((await metrics(label)).left); // indented behind the rule
  // The current page: aria-current, semibold, tinted.
  const current = sub.getByRole("link", { name: "Invoices" });
  await expect(current).toHaveAttribute("aria-current", "page");
  expect((await metrics(current)).weight).toBeGreaterThan(second.weight);
});

test.describe("phone width (360 px)", () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test("Home signed in: no sideways scroll; the drawer keeps the hierarchy", async ({ page, runtime }) => {
    await home(page, runtime, COMPANY);
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(await overflow()).toBeLessThanOrEqual(0);

    await page.getByRole("button", { name: "Menu" }).click();
    const drawer = page.getByRole("dialog", { name: "Menu" });
    const heading = drawer.getByRole("heading", { name: "Sales" });
    const link = drawer.getByRole("link", { name: "Quotes" });
    const h = await metrics(heading);
    const l = await metrics(link);
    expect(l.size).toBeLessThan(h.size);
    expect(l.weight).toBeLessThan(h.weight);
    expect(l.left).toBeGreaterThan(h.left);
    await page.keyboard.press("Escape");
  });

  test("the sample Home (/try, signed out): no sideways scroll either", async ({ page }) => {
    await page.goto("/try");
    await expect(card(page, "Your summary")).toContainText("£12,480.00");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("axe: Home signed in has no serious or critical violations", async ({ page, runtime }) => {
    await home(page, runtime, SOLE_TRADER);
    await page.waitForLoadState("networkidle");
    const { violations } = await new AxeBuilder({ page }).analyze();
    const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
});
