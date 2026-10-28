import type { Locator, Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Keyboard only: Home → Review → scan and approve the gold receipt → Settings, change tab → Ask a question, with
 * Tab, Shift+Tab, Enter, arrows, Escape and Review's shortcuts. No mouse after page.goto("/").
 * Every Tab stop must show a focus ring and move focus on (never stuck); a dialog keeps focus inside while open
 * and gives it back to whatever opened it.
 */

interface Stop {
  key: string; // identity of the element, to spot focus that does not move
  name: string;
  href: string | null;
  nav: string | null;
  role: string | null;
  ringed: boolean;
  inDialog: boolean;
  segments: number; // Tab stops inside the element: Chromium tabs through a date field's three parts and its calendar button
}

/** The focused element, or null when focus is on the body or has left the page (browser UI). */
function focused(page: Page): Promise<Stop | null> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return null;
    // A ring on the element itself, or on the pill that carries a borderless input's ring (.focus-ring-within).
    // Tailwind 4's outline-none is a 2px *transparent* outline, so the colour must be opaque too.
    const ring = (n: Element | null) => {
      if (!n) return false;
      const s = getComputedStyle(n);
      const transparent = s.outlineColor === "transparent" || /^rgba\(.*,\s*0\)$/.test(s.outlineColor);
      return s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2 && !transparent;
    };
    const label = el.getAttribute("aria-label") ?? (el as HTMLInputElement).labels?.[0]?.textContent ?? el.textContent ?? "";
    const r = el.getBoundingClientRect();
    return {
      key: `${el.tagName}|${el.id}|${label}|${Math.round(r.x)},${Math.round(r.y)}`,
      name: label.trim().replace(/\s+/g, " ").slice(0, 80),
      href: el.getAttribute("href"),
      nav: el.closest("nav")?.getAttribute("aria-label") ?? null,
      role: el.getAttribute("role"),
      // A date field keeps focus on its calendar button without :focus-visible; globals.css rings it on :focus-within.
      ringed:
        (el.matches(":focus-visible") || (el instanceof HTMLInputElement && el.type === "date" && el.matches(":focus-within"))) &&
        (ring(el) || ring(el.closest(".focus-ring-within"))),
      inDialog: !!el.closest("dialog[open]"),
      segments: el instanceof HTMLInputElement && el.type === "date" ? 4 : 1,
    };
  });
}

/** Press Tab (or Shift+Tab) until `want` holds. Each stop must be visibly focused and differ from the last. */
async function tabTo(page: Page, want: (s: Stop) => boolean, what: string, { back = false, max = 80 } = {}): Promise<Stop> {
  let last: string | null = null;
  let repeats = 0; // presses that stayed on the same element, moving between its segments
  for (let i = 0; i < max; i++) {
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
    const s = await focused(page);
    if (!s) {
      last = null; // focus went to the browser UI past the end of the page; the next Tab comes back in
      repeats = 0;
      continue;
    }
    expect(s.ringed, `no visible focus on "${s.name}" (${s.key})`).toBe(true);
    repeats = s.key === last ? repeats + 1 : 0;
    expect(repeats, `focus stuck on "${s.name}"`).toBeLessThan(s.segments);
    last = s.key;
    if (want(s)) return s;
  }
  throw new Error(`${what}: not reached in ${max} Tab presses`);
}

/** Open a dialog with `open`, check Tab stays inside it, close it with Escape and check focus went back. */
async function dialogRoundTrip(page: Page, open: () => Promise<void>, dialog: Locator, back: Locator) {
  await open();
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Tab");
    const s = await focused(page);
    if (s) expect(s.inDialog, `Tab left the open dialog for "${s.name}"`).toBe(true); // null: the browser UI, then back in
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(back).toBeFocused();
}

const inMain = (href: string) => (s: Stop) => s.href === href && s.nav === "Main";

test("keyboard only: Home → Review → approve → Settings tab → Ask", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.dropInInbox(); // the gold receipt waits in 00 Inbox

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Good morning, Sam" })).toBeVisible();
  await page.waitForLoadState("networkidle");

  // Home → Review, from the menu bar: Enter opens Purchases, Tab reaches Bills (Review).
  await tabTo(page, (s) => s.nav === "Main" && s.name.startsWith("Purchases"), "Purchases in the menu bar");
  await page.keyboard.press("Enter");
  await tabTo(page, inMain("/review"), "Bills (Review) under Purchases");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/review$/);

  // Scan, then J picks the card, E opens the edit sheet (Escape gives focus back to the card), A approves.
  await tabTo(page, (s) => s.name === "Scan 00 Inbox now", "Scan 00 Inbox now");
  await page.keyboard.press("Enter");
  // The first read in a fresh runtime takes ~10 s (cold stub AI) when this spec runs on its own.
  await expect(page.getByRole("status").filter({ hasText: "new proposal" })).toHaveText("1 new proposal", { timeout: 30_000 });
  await page.keyboard.press("j");
  const card = page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" });
  await expect(card).toBeFocused();
  await dialogRoundTrip(page, () => page.keyboard.press("e"), page.getByRole("dialog", { name: "Edit Novex Office Supplies Ltd" }), card);
  await page.keyboard.press("a");
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("Approved · posted to your books · U to undo");
  await expect(card).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 2, name: /^Nothing waiting/ })).toBeFocused(); // focus moved on, not lost

  // Settings: Tab reaches the selected tab (one stop for the tab list), the arrow keys change it.
  await tabTo(page, (s) => s.href === "/settings" && s.nav === "About", "Settings in the footer");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/settings$/);
  await tabTo(page, (s) => s.role === "tab", "the Settings tab list");
  await expect(page.getByRole("tab", { name: "Connection" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "AI", exact: true })).toBeFocused();
  await expect(page.getByRole("tab", { name: "AI", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: "AI" })).toBeVisible();

  // Ask: back up the page to the menu bar with Shift+Tab, open the explainer and close it, then ask.
  await tabTo(page, (s) => s.href === "/ask" && s.name === "Ask", "Ask in the menu bar", { back: true });
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/ask$/);
  await expect(page.getByRole("heading", { name: "No questions yet" })).toBeVisible(); // live, not the sample
  const explain = page.getByRole("button", { name: "Explain: Where answers come from" });
  await tabTo(page, (s) => s.name === "Explain: Where answers come from", "the Ask explainer");
  await dialogRoundTrip(page, () => page.keyboard.press("Enter"), page.getByRole("dialog", { name: "Where answers come from" }), explain);
  await tabTo(page, (s) => s.name === "Ask your books", "the question box");
  await page.keyboard.type("How much VAT do I owe this quarter?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article")).toContainText("Your net VAT (Box 5) for this quarter is");
});

test("Tab runs through each main page and out the other end: never trapped, focus always visible", async ({ page, runtime }) => {
  test.slow(); // six pages, every focusable element: well over 30 s when the suite runs in parallel
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();
  for (const path of ["/", "/review", "/settings", "/ask", "/vat", "/files"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    // The footer's last link is the end of every page: reaching it, then leaving the page, means nothing held focus.
    await tabTo(page, (s) => s.nav === "About" && s.name === "Settings", `${path}: the footer`, { max: 150 });
    await page.keyboard.press("Tab");
    expect(await focused(page), `${path}: focus should leave the page after the footer`).toBeNull();
  }
});

test("Explain drawer: a click inside stays open, the backdrop closes it, focus returns, it opens again", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();
  await page.goto("/ask");
  const explain = page.getByRole("button", { name: "Explain: Where answers come from" });
  const dialog = page.getByRole("dialog", { name: "Where answers come from" });
  await explain.click();
  await expect(dialog).toBeVisible();
  // The panel's own padding, above the heading: inside the drawer, so it must not count as the backdrop.
  const box = (await dialog.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + 6);
  await expect(dialog).toBeVisible();
  await page.mouse.click(5, 5); // the backdrop, well left of the side drawer
  await expect(dialog).toHaveCount(0);
  await expect(explain).toBeFocused();
  await expect(explain).toHaveAttribute("aria-expanded", "false");
  await explain.click();
  await expect(dialog).toBeVisible();
  await page.getByRole("button", { name: "Close explanation" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(explain).toBeFocused();
});
