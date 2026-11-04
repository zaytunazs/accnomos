import type { Page, Request } from "@playwright/test";
import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";
import { RUNTIME_URL } from "./env.mjs";

/**
 * "Which AI answers first" (lib/ai-route.ts, components/AiRouteChoice.tsx): the three options on the AI step of
 * /connect and in Settings › AI, the local-only warning, the choice kept across a reload, and `X-AI-Route` on
 * runtime requests once a choice is saved (never before).
 */

/** Every runtime request after this call, with all its headers (preflights left out). */
function recordRuntime(page: Page): { url: string; method: string; headers: Promise<Record<string, string>> }[] {
  const seen: { url: string; method: string; headers: Promise<Record<string, string>> }[] = [];
  page.on("request", (r: Request) => {
    if (!r.url().startsWith(RUNTIME_URL) || r.method() === "OPTIONS") return;
    seen.push({ url: r.url(), method: r.method(), headers: r.allHeaders() });
  });
  return seen;
}

async function testConnection(page: Page): Promise<Record<string, string>> {
  const req = page.waitForRequest((r) => r.url() === `${RUNTIME_URL}/ai/test` && r.method() === "POST");
  await page.getByRole("button", { name: "Test connection" }).click();
  return (await req).allHeaders();
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
});

test("AI step: three options, the local-only warning, saved and sent as X-AI-Route", async ({ page }) => {
  await page.goto("/connect/ai");
  const section = page.getByRole("region", { name: "Which AI answers first" });
  const group = section.getByRole("radiogroup", { name: "Which AI answers first" });
  await expect(group.getByRole("radio")).toHaveCount(3);
  const metaFirst = group.getByRole("radio", { name: /^Meta Model API first/ });
  const localFirst = group.getByRole("radio", { name: /^Local model first, Meta API when unsure/ });
  const localOnly = group.getByRole("radio", { name: /^Local model only/ });
  await expect(metaFirst).toBeChecked(); // the default, shown before anything is saved
  await expect(localFirst).not.toBeChecked();
  await expect(section).toContainText("RECOMMENDED");

  // The warning sits under "Local model only" all the time, and stands out once it is picked.
  const warning = page.getByTestId("ai-route-local-warning");
  await expect(warning).toBeVisible();
  await expect(warning).toHaveAttribute("data-selected", "false");
  for (const line of [
    "Slower: reading a receipt or invoice can take a minute or more.",
    "Less accurate on messy photos, handwriting and long PDFs, so more items are left for you to check.",
    "No voice input: speech-to-text (Muse Voice Transcribe) runs on the Meta Model API.",
    "If the local model is offline, AI features wait; nothing falls back.",
    "Every number is still checked by code before anything is saved, whichever you pick.",
  ]) {
    await expect(warning).toContainText(line);
  }

  // Nothing saved yet: no header, so the runtime keeps its own default.
  expect(await page.evaluate(() => window.localStorage.getItem("accnomos.ai.route"))).toBeNull();
  expect((await testConnection(page))["x-ai-route"]).toBeUndefined();

  await localOnly.check();
  await expect(localOnly).toBeChecked();
  await expect(metaFirst).not.toBeChecked();
  await expect(warning).toHaveAttribute("data-selected", "true");
  await expect(section.getByRole("status")).toHaveText("Saved on this device.");
  expect(await page.evaluate(() => window.localStorage.getItem("accnomos.ai.route"))).toBe("local_only");
  expect((await testConnection(page))["x-ai-route"]).toBe("local_only");

  await page.reload();
  await expect(page.getByRole("radiogroup", { name: "Which AI answers first" }).getByRole("radio", { name: /^Local model only/ })).toBeChecked();
});

test("Settings › AI: the choice persists across a reload and every books request carries it", async ({ page }) => {
  await page.goto("/settings");
  let panel = await settingsTab(page, "AI");
  let group = panel.getByRole("radiogroup", { name: "Which AI answers first" });
  await expect(group.getByRole("radio")).toHaveCount(3);
  await group.getByRole("radio", { name: /^Local model first, Meta API when unsure/ }).check();
  await expect(panel.getByRole("region", { name: "Which AI answers first" }).getByRole("status")).toHaveText("Saved on this device.");

  const seen = recordRuntime(page);
  await page.reload();
  panel = await settingsTab(page, "AI");
  group = panel.getByRole("radiogroup", { name: "Which AI answers first" });
  await expect(group.getByRole("radio", { name: /^Local model first, Meta API when unsure/ })).toBeChecked();
  await expect(group.getByRole("radio", { name: /^Meta Model API first/ })).not.toBeChecked();
  await expect(page.getByTestId("ai-route-local-warning")).toHaveAttribute("data-selected", "false");

  // The signed-in page's own runtime calls (the books, with a Graph token) carry the saved route.
  await expect.poll(() => seen.length).toBeGreaterThan(0);
  const books: Record<string, string>[] = [];
  for (const r of seen) {
    const h = await r.headers;
    if (h["x-graph-token"]) books.push(h);
  }
  expect(books.length, "no signed-in runtime request after the reload").toBeGreaterThan(0);
  for (const h of books) expect(h["x-ai-route"]).toBe("local_first");

  expect((await testConnection(page))["x-ai-route"]).toBe("local_first");
});
