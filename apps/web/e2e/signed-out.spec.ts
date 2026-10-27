import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { PAGES } from "./pages";

/**
 * Signed-out sweep: every page shows the single SAMPLE label once (the
 * banner), every CTA uses the one wording for its page, and every sample
 * action works locally (or is disabled with a reason) — never a dead button.
 * Runs at phone and desktop widths.
 */

const LABEL = "SAMPLE — FICTIONAL COMPANY";
const KNOWN = new Set(PAGES);
// The onboarding flow is the CTA's destination: its buttons start real
// Microsoft sign-in, which never runs in the static export.
const CONNECT_PAGES = new Set(["/connect", "/connect/ai", "/connect/business", "/connect/ready"]);

const ctaName = (route: string) => (route === "/" ? "Connect your OneDrive" : "Sign in to see your books");

test.describe("signed out at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  // Button-heavy pages re-load per button; give them room.
  test.describe.configure({ timeout: 120_000 });
  for (const route of PAGES) {
    test(`${route}: one label, CTA wording, live controls`, async ({ page }) => {
      await checkPage(page, route);
    });
  }
});

test.describe("signed out at 1280px", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  test.describe.configure({ timeout: 120_000 });
  for (const route of PAGES) {
    test(`${route}: one label, CTA wording, live controls`, async ({ page }) => {
      await checkPage(page, route);
    });
  }
});

async function checkPage(page: Page, route: string) {
  // window.print() would open the browser dialog: mark it instead.
  await page.addInitScript(() => {
    (window as unknown as { __printed: boolean }).__printed = false;
    window.print = () => {
      (window as unknown as { __printed: boolean }).__printed = true;
    };
  });
  await page.goto(route);
  const main = page.locator("main");

  // The one label, exactly once (the banner); sample fallbacks never repeat it.
  const hits = await page.evaluate((label) => document.body.innerText.split(label).length - 1, LABEL);
  expect(hits, `${route}: "${LABEL}" occurrences`).toBe(1);

  // No "coming soon", and no live-looking "today" dates in samples.
  await expect(main, `${route}: no coming soon`).not.toContainText(/coming soon/i);
  await expect(main, `${route}: no live dates`).not.toContainText(/due today|what the agents did today/i);

  // Every link goes somewhere real: no dead "#" links, every anchor lands,
  // every internal path is a known page.
  const links = page.locator('main a[href], header a[href], aside a[href], footer a[href]');
  const linkCount = await links.count();
  for (let i = 0; i < linkCount; i++) {
    const href = (await links.nth(i).getAttribute("href")) ?? "";
    expect(href, `${route}: link ${i} has a destination`).not.toMatch(/^(#)?$/);
    if (href.startsWith("#")) {
      const landed = await page.evaluate((id) => document.getElementById(id) !== null, href.slice(1));
      expect(landed, `${route}: anchor ${href} exists`).toBe(true);
    } else if (href.startsWith("/")) {
      const path = href.split(/[?#]/)[0] || "/";
      expect(KNOWN.has(path), `${route}: link to known page ${href}`).toBe(true);
    }
  }

  if (CONNECT_PAGES.has(route)) return; // the destination itself carries no CTA

  // The one CTA wording for the page, always to /connect.
  const ctas = page.getByRole("link", { name: ctaName(route) });
  await expect(ctas.first(), `${route}: CTA "${ctaName(route)}"`).toBeVisible();
  for (const cta of await ctas.all()) {
    await expect(cta, `${route}: CTA destination`).toHaveAttribute("href", "/connect");
  }

  // Every enabled button does something observable (navigation, dialog,
  // download, print or a changed page); every disabled one names its reason.
  const buttons = page.getByRole("button");
  const count = await buttons.count();
  for (let i = 0; i < count; i++) {
    await page.goto(route);
    const btn = page.getByRole("button").nth(i);
    const name = (await btn.getAttribute("aria-label")) ?? ((await btn.innerText()).trim().slice(0, 40));
    if (!(await btn.isEnabled())) {
      const reason = (await btn.getAttribute("title")) ?? (await btn.getAttribute("aria-describedby"));
      expect(reason?.trim() || "", `${route}: disabled button "${name}" names its reason`).not.toBe("");
      continue;
    }
    const before = await page.evaluate(() => ({
      url: location.href,
      html: document.body.innerHTML,
      printed: (window as unknown as { __printed: boolean }).__printed === true,
    }));
    let downloaded = false;
    const onDownload = () => {
      downloaded = true;
    };
    page.on("download", onDownload);
    await btn.click({ timeout: 10_000 });
    await page.waitForTimeout(250);
    page.off("download", onDownload);
    const after = await page.evaluate(() => ({
      url: location.href,
      html: document.body.innerHTML,
      printed: (window as unknown as { __printed: boolean }).__printed === true,
    }));
    const dialogOpen = await page.getByRole("dialog").first().isVisible().catch(() => false);
    const worked =
      after.url !== before.url ||
      after.html !== before.html ||
      after.printed !== before.printed ||
      downloaded ||
      dialogOpen;
    expect(worked, `${route}: enabled button "${name}" does something`).toBe(true);
    if (dialogOpen) await page.keyboard.press("Escape");
  }
}
