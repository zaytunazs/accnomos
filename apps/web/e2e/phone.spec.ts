import type { Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";
import { PAGES } from "./pages"; // every page of the static export, at phone width (project "phone"), signed in with a posted receipt

/** The pages used most on a phone, with the control each must show without scrolling sideways. */
const NARROW: [string, string][] = [
  ["/", "Ask"], ["/review", "Scan 00 Inbox now"], ["/ask", "Ask"], ["/vat", "Add to calendar"], ["/settings", "Business"],
];

/** Every page in the app nav (AppNav.tsx links plus Settings), checked at the narrowest common phone width. */
const NAV_PAGES = ["/", "/review", "/ask", "/invoices", "/bank", "/vat", "/month-end", "/jobs", "/payroll", "/reports", "/contacts", "/vehicles", "/files", "/settings"];

test.describe("360 px wide (small Android), every nav page", () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test.beforeEach(async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.postGold();
  });

  for (const path of NAV_PAGES) {
    test(`${path}: no horizontal scroll once loaded`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("main").first()).toBeVisible();
      // Data has finished loading: no skeleton, busy region, "Loading…" text or pulsing placeholder, and layout has been stable for two frames.
      await page.waitForFunction(
        () =>
          !document.querySelector("[aria-busy=true], .animate-pulse") &&
          ![...document.querySelectorAll("main *")].some((el) => el.children.length === 0 && /^Loading\b/.test(el.textContent ?? "")),
        undefined,
        { timeout: 15_000 },
      );
      await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
      const { scroll, client, widest } = await page.evaluate(() => {
        const root = document.documentElement;
        let widest = "";
        let max = root.clientWidth;
        for (const el of document.querySelectorAll("body *")) {
          if (!el.checkVisibility()) continue;
          const r = el.getBoundingClientRect();
          if (r.width > 0 && r.right > max) {
            max = r.right;
            const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 4).join(".") : "";
            widest = `<${el.tagName.toLowerCase()}${cls ? "." + cls : ""}> right edge ${Math.round(r.right)}px: "${(el.textContent ?? "").trim().slice(0, 50)}"`;
          }
        }
        return { scroll: root.scrollWidth, client: root.clientWidth, widest };
      });
      expect(client).toBe(360);
      expect(scroll, `${path}: page is ${scroll}px wide in a ${client}px viewport. Widest element: ${widest || "none past the edge"}`).toBeLessThanOrEqual(client);
    });
  }
});

test.describe("390 px wide (iPhone 12–15)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.postGold();
  });

  for (const [path, control] of NARROW) {
    test(`${path}: no horizontal scroll, every button on screen`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("main").getByRole(path === "/settings" ? "tab" : path === "/vat" ? "link" : "button", { name: control, exact: true }).first()).toBeInViewport();
      const { scroll, width, offscreen } = await page.evaluate(() => {
        // Buttons inside a sideways-scrolling table are reachable by scrolling it; everything else must fit.
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
      expect(scroll, `${path}: page is ${scroll}px wide`).toBeLessThanOrEqual(width);
      expect(offscreen, `${path}: buttons cut off at the edge`).toEqual([]);
    });
  }
});

test.describe("phone viewport smoke", () => {
  test.beforeEach(async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.postGold();
  });

  for (const path of PAGES) {
    test(`${path} has no horizontal scroll`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      const res = await page.goto(path);
      expect(res?.status()).toBe(200);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main").first()).toBeVisible();
      const { scroll, width } = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        width: window.innerWidth,
      }));
      expect(scroll, `${path}: page is ${scroll}px wide in a ${width}px viewport`).toBeLessThanOrEqual(width);
      expect(errors).toEqual([]);
    });
  }
});

test.describe("Review at 390 px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("signed-out sample: no horizontal scroll, action rows never wrap, approve and undo work", async ({ page }) => {
    await page.goto("/review");
    await expect(page.getByText("SAMPLE — FICTIONAL COMPANY · demo data only")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
    expect(scroll, `review is ${scroll}px wide in a ${width}px viewport`).toBeLessThanOrEqual(width);

    // Approve, Edit and Reject sit on one line on every card.
    const rows = await page.getByRole("button", { name: /^Approve .* and post to books$/ }).evaluateAll((buttons) =>
      buttons.map((b) => {
        const row = [...b.parentElement!.children].map((c) => c.getBoundingClientRect());
        return { tops: new Set(row.map((r) => Math.round(r.top))).size, right: Math.max(...row.map((r) => r.right)) };
      }),
    );
    expect(rows.length).toBe(4);
    for (const r of rows) {
      expect(r.tops).toBe(1);
      expect(r.right).toBeLessThanOrEqual(390);
    }

    const screwfix = page.getByRole("region", { name: "Screwfix · £38.47" });
    await screwfix.getByRole("button", { name: /^Approve Screwfix/ }).click();
    await expect(screwfix).toHaveCount(0);
    await page.keyboard.press("u");
    await expect(screwfix).toBeVisible();
  });
});

test.describe("brand images at the size used, and reduced motion", () => {
  /** The /brand files the signed-out Home (the one page with the hero) asks for at this width. */
  async function brandRequests(page: Page): Promise<string[]> {
    const seen: string[] = [];
    page.on("request", (r) => {
      const path = new URL(r.url()).pathname;
      if (path.startsWith("/brand/")) seen.push(path);
    });
    await page.goto("/");
    await expect(page.getByRole("link", { name: "See the demo books" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    return seen;
  }

  test("phone (412 px): the 800 px hero only; never hero.jpg or the Play feature graphic", async ({ page }) => {
    expect(await brandRequests(page)).toEqual(["/brand/hero-800.jpg"]);
  });

  test.describe("1280 px", () => {
    test.use({ viewport: { width: 1280, height: 800 } });
    test("the full hero, still never the feature graphic", async ({ page }) => {
      expect(await brandRequests(page)).toEqual(["/brand/hero.jpg"]);
    });
  });

  test("prefers-reduced-motion: pulses stop and transitions are instant; otherwise they run", async ({ page }) => {
    const motion = () =>
      page.evaluate(() => {
        const probe = document.createElement("span");
        probe.className = "animate-pulse transition-all";
        document.body.append(probe);
        const s = getComputedStyle(probe);
        const out = { iterations: s.animationIterationCount, transition: parseFloat(s.transitionDuration) };
        probe.remove();
        return out;
      });
    await page.goto("/privacy");
    expect(await motion()).toEqual({ iterations: "infinite", transition: 0.15 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const reduced = await motion();
    expect(reduced.iterations).toBe("1");
    expect(reduced.transition).toBeLessThan(0.001);
  });
});
