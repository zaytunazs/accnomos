// Screenshots of the public website for review (docs/reviews/marketing/shots/), at 1280 and 360 px.
// Needs the test-mode export served and the test runtime up, as for `pnpm run e2e:test` (WEB_URL from e2e/env.mjs).
// Run: node e2e/marketing-shots.mjs
import { mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "@playwright/test";
import { WEB_URL } from "./env.mjs";

const OUT = path.resolve(import.meta.dirname, "../../../docs/reviews/marketing/shots");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
for (const [w, h, tag] of [[1280, 800, "1280"], [360, 740, "360"]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, reducedMotion: "reduce", locale: "en-GB" });
  const shot = (name, opts = {}) => page.screenshot({ path: path.join(OUT, `${name}-${tag}.png`), ...opts });
  await page.goto(`${WEB_URL}/`);
  await page.waitForLoadState("networkidle");
  await shot("landing-top");
  // Scroll through once so every lazy image loads before the full-page shot.
  for (let y = 0; y < (await page.evaluate(() => document.body.scrollHeight)); y += h / 2) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(120);
  }
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot("landing-full", { fullPage: true });
  if (w < 1024) {
    await page.getByRole("button", { name: "Menu" }).click();
    await shot("menu-open");
    await page.keyboard.press("Escape");
  }
  await page.locator("#chat-launcher").click();
  const chat = page.getByRole("dialog", { name: "Ask about Accnomos" });
  await chat.getByRole("button", { name: "Where are my books stored?" }).click();
  await chat.getByText("Based on our notes").waitFor();
  const input = chat.getByRole("textbox");
  await input.fill("What's the weather in Paris?");
  await input.press("Enter");
  await chat.getByText("Please email the team").waitFor();
  await shot("chat");
  await page.keyboard.press("Escape");
  for (const p of ["privacy", "how-it-works"]) {
    await page.goto(`${WEB_URL}/${p}`);
    await page.waitForLoadState("networkidle");
    await shot(p);
  }
  await page.goto(`${WEB_URL}/try`);
  await page.waitForLoadState("networkidle");
  await shot("try");
  await page.close();
}
await browser.close();
console.log(`wrote ${OUT}`);
