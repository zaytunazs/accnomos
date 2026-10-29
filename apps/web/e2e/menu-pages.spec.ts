import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Every item in the menu bar opens a page of its own (lib/nav.ts): its own URL and its own main heading, so no two
 * items land on the same page or the same anchor. The same page may sit in two groups only under the same label
 * (Customers under Sales and under Contacts). The current page's item, and only that one, is highlighted.
 */

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await createBooksFolder(page);
});

test("every menu item opens its own page with its own heading", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  const items: { group: string; label: string; href: string }[] = [];
  for (const button of await nav.getByRole("button").all()) {
    const group = (await button.innerText()).split("\n")[0].trim();
    await button.click();
    const id = await button.getAttribute("aria-controls");
    for (const link of await page.locator(`#${id} a`).all()) {
      items.push({ group, label: (await link.innerText()).split("\n")[0].trim(), href: (await link.getAttribute("href")) ?? "" });
    }
    await page.keyboard.press("Escape");
  }
  expect(items.length).toBeGreaterThan(20);

  // No anchors or query strings: an item is a page, not a place on another item's page.
  for (const i of items) expect(i.href, `${i.group} › ${i.label}`).not.toMatch(/[#?]/);

  // One page per label, and one label per page.
  const byHref = new Map<string, Set<string>>();
  for (const i of items) byHref.set(i.href, (byHref.get(i.href) ?? new Set()).add(i.label));
  for (const [href, labels] of byHref) expect([...labels], `labels opening ${href}`).toHaveLength(1);

  // Each page answers with its own main heading.
  const headings = new Map<string, string>();
  for (const href of byHref.keys()) {
    await page.goto(href);
    const h1 = page.getByRole("heading", { level: 1 }).first();
    await expect(h1, href).toBeVisible();
    await expect(page.getByRole("heading", { name: "Page not found" }), href).toHaveCount(0);
    headings.set(href, (await h1.innerText()).trim());
  }
  const seen = new Map<string, string>();
  for (const [href, h] of headings) {
    expect(seen.get(h), `"${h}" is the heading of both ${seen.get(h)} and ${href}`).toBeUndefined();
    seen.set(h, href);
  }
});

test("the Accounting bank items each have a page; only the current item is highlighted", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const [label, path, heading] of [
    ["Bank accounts", "/bank", "Bank"],
    ["Bank rules", "/bank/rules", "Bank rules"],
    ["Reconcile", "/bank/reconcile", "Reconcile"],
  ] as const) {
    await page.goto("/");
    await nav.getByRole("button", { name: /^Accounting/ }).click();
    await nav.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
    await nav.getByRole("button", { name: /^Accounting/ }).click();
    await expect(nav.getByRole("link", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  }
  await page.screenshot({ path: "../../docs/reviews/app-shell/menu-reconcile-1440.png" });
});
