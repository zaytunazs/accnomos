import type { Page } from "@playwright/test";
import { RUNTIME_URL } from "./env.mjs";
import { createBooksFolder, expect, signIn, test, USER } from "./fixtures";

/**
 * Linked profiles (src/lib/profiles.ts) and the menu bar (src/components/TopBar.tsx, src/lib/nav.ts).
 * One Microsoft account is one profile; the test sign-in (src/lib/msal-test.ts) adds Jo as a second account, whose
 * token "test-token.jo" the runtime gives a OneDrive of its own.
 */

const JO = "jo@personal.example";
const JO_TOKEN = "test-token.jo";

const mainNav = (page: Page) => page.getByRole("navigation", { name: "Main" });
const switcher = (page: Page) => page.getByRole("button", { name: /^Profile: / });

test("menu bar: groups as dropdowns, keyboard and screen-reader friendly, only pages in this build", async ({ page }) => {
  test.slow(); // opens every group and fetches every linked page
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
  const nav = mainNav(page);
  await expect(nav.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  for (const g of ["Sales", "Purchases", "Reporting", "Accounting", "Tax", "Payroll", "Contacts"]) {
    await expect(nav.getByRole("button", { name: new RegExp(`^${g}`) })).toHaveAttribute("aria-expanded", "false");
  }
  await expect(nav.getByRole("button", { name: "Personal" })).toHaveCount(0); // not personal books

  // Keyboard: ↓ opens Sales on its first link (Sales overview, now that the sales pages are in this build), ↓ moves
  // in menu order, Escape closes and gives focus back to the button.
  const sales = nav.getByRole("button", { name: "Sales" });
  await sales.focus();
  await page.keyboard.press("ArrowDown");
  await expect(sales).toHaveAttribute("aria-expanded", "true");
  await expect(nav.getByRole("link", { name: "Sales overview" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(nav.getByRole("link", { name: "Invoices" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(sales).toHaveAttribute("aria-expanded", "false");
  await expect(sales).toBeFocused();
  await expect(nav.getByRole("link", { name: "Invoices" })).toBeHidden();

  // Pages another branch has not landed are not linked at all (no balance sheet page yet).
  await sales.click();
  for (const name of ["Sales overview", "Quotes", "Products and services", "Repeating"]) {
    await expect(nav.getByRole("link", { name })).toBeVisible(); // claude/sales-purchases' pages, now in the build
  }
  await sales.click();
  await nav.getByRole("button", { name: "Reporting" }).click();
  await expect(nav.getByRole("link", { name: "Balance sheet" })).toHaveCount(0);
  await nav.getByRole("button", { name: "Reporting" }).click();
  await sales.click();
  // Enter follows a link; the new page closes the group and marks where you are.
  await nav.getByRole("link", { name: "Invoices" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
  await expect(sales).toHaveAttribute("aria-expanded", "false");
  await nav.getByRole("button", { name: "Sales" }).click();
  await expect(nav.getByRole("link", { name: "Invoices" })).toHaveAttribute("aria-current", "page");

  // Every link the menu shows opens a page of this build (no 404).
  const hrefs = new Set<string>();
  for (const g of ["Sales", "Purchases", "Reporting", "Accounting", "Tax", "Payroll", "Contacts"]) {
    await nav.getByRole("button", { name: new RegExp(`^${g}`) }).click();
    for (const href of await nav.getByRole("link").evaluateAll((els) => els.map((e) => e.getAttribute("href") ?? ""))) hrefs.add(href.split(/[?#]/)[0]);
  }
  for (const href of hrefs) {
    const r = await page.request.get(href);
    expect(r.status(), href).toBe(200);
  }

  // The account menu: the signed-in email and "Sign out of this one".
  await page.getByRole("button", { name: `Account: ${USER}` }).click();
  const account = page.getByRole("menu", { name: "Account" });
  await expect(account).toContainText(USER);
  await expect(account.getByRole("menuitem", { name: "Sign out of this one" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: `Account: ${USER}` })).toBeFocused();
});

test("two linked accounts: add one, set it up as personal, switch in one click; books and menus never mix", async ({ page, runtime }) => {
  test.slow(); // two sign-ins, two folders, three full page loads
  await runtime.resetAccount(JO_TOKEN);
  await runtime.api("PUT", "/profile", {
    name: "Sam Builds Ltd",
    kind: "company",
    settings: { company_number: "01234567", vat_registered: true },
  });
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
  await expect(switcher(page)).toContainText("Sam Builds Ltd");
  await expect(switcher(page)).toContainText("Company");

  // Add Jo from the profile menu.
  await switcher(page).click();
  const menu = page.getByRole("menu", { name: "Profiles" });
  await expect(menu.getByRole("menuitemradio", { name: /Sam Builds Ltd/ })).toHaveAttribute("aria-checked", "true");
  await menu.getByRole("menuitem", { name: "Add another account / business" }).click();
  await expect(page).toHaveURL(/\/connect\?add=1$/);
  await page.getByRole("button", { name: "Sign in with another Microsoft account" }).click();
  await page.getByRole("button", { name: "Create my Accnomos folder" }).click();
  await expect(page.getByText("Your folder is ready.")).toBeVisible();
  await expect(page.getByRole("main").getByText(JO, { exact: true })).toBeVisible(); // the Connect page's line (the menu bar shows it too)

  // Jo's books are personal. Every runtime call now carries Jo's token.
  const tokens: string[] = [];
  page.on("request", (r) => {
    const t = r.headers()["x-graph-token"];
    if (t) tokens.push(t);
  });
  await page.getByRole("link", { name: "Set up this profile" }).click();
  const profile = page.getByRole("region", { name: "Profile" });
  await profile.getByLabel("Profile name").fill("Jo at home");
  await profile.getByRole("radio", { name: /Personal/ }).check();
  await profile.getByRole("button", { name: "Save profile" }).click();
  await expect(profile.getByRole("status")).toHaveText("Saved to your OneDrive.");
  expect(new Set(tokens)).toEqual(new Set([JO_TOKEN]));

  await page.goto("/");
  await expect(switcher(page)).toContainText("Jo at home");
  await expect(switcher(page)).toContainText("Personal");
  const nav = mainNav(page);
  await expect(nav.getByRole("button", { name: "Purchases" })).toBeVisible();
  for (const gone of ["Sales", "Payroll", "Tax"]) await expect(nav.getByRole("button", { name: gone })).toHaveCount(0);
  await nav.getByRole("button", { name: "Reporting" }).click();
  await expect(nav.getByRole("link", { name: "VAT return" })).toHaveCount(0);
  // The runtime agrees: Jo's books have no VAT return.
  const vat = await page.request.get(`${RUNTIME_URL}/books/vat`, { headers: { "X-Graph-Token": JO_TOKEN } });
  expect(vat.status()).toBe(404);
  expect((await vat.json()).detail).toContain("personal profile");

  // Switch back to Sam in one click: Sam's token, Sam's company menu.
  tokens.length = 0;
  await switcher(page).click();
  await page.getByRole("menuitemradio", { name: /Sam Builds Ltd/ }).click();
  await expect(switcher(page)).toContainText("Sam Builds Ltd");
  await expect(mainNav(page).getByRole("button", { name: "Sales" })).toBeVisible();
  await expect(mainNav(page).getByRole("button", { name: "Tax" })).toBeVisible();
  await expect.poll(() => tokens.length).toBeGreaterThan(0);
  expect(new Set(tokens)).toEqual(new Set(["test-token"]));

  // Both are listed, the current one checked.
  await switcher(page).click();
  await expect(page.getByRole("menuitemradio", { name: /Sam Builds Ltd/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("menuitemradio", { name: /Jo at home/ })).toHaveAttribute("aria-checked", "false");
});

test.describe("at 360 px", () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test("the groups are in a drawer; it keeps focus and Escape gives it back", async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/");
    const open = page.getByRole("button", { name: "Menu", exact: true });
    await expect(switcher(page)).toBeVisible();
    await open.click();
    const drawer = page.getByRole("dialog", { name: "Menu" });
    await expect(drawer.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Invoices" })).toBeVisible();
    await expect(drawer.getByRole("heading", { name: "Accounting" })).toBeVisible();
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(360); // nothing pushes the page sideways
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(open).toBeFocused();
  });
});
