import { existsSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * /meta-models (src/app/meta-models/page.tsx, data in src/lib/meta-models-page.ts): one page saying which Meta model
 * does which job. It lists every model in use, each overview row lands on its section, every report link points at a
 * file committed in this repository, and the page names no hardware and no other company's engine. Reached from the
 * public footer, the app footer, /judges and the Home summary card.
 */
const MODELS = [
  ["muse-spark", "Muse Spark 1.3"],
  ["muse-glimmer", "Muse Glimmer 30B"],
  ["muse-spark-open", "Muse Spark Open"],
  ["muse-voice-transcribe", "Muse Voice Transcribe"],
  ["sam", "Segment Anything 3.1"],
  ["muse-image", "Muse Image"],
] as const;
const ROOT = join(process.cwd(), "..", "..");
const BLOB = "https://github.com/zaytunazs/accnomos/blob/main/";
const NOT_NAMED = /DGX|Ollama|vLLM|Whisper|Kokoro|Qwen|ComfyUI|Baseten|L40S|coming soon|\bbeta\b|early access|launching/i;

async function open(page: Page) {
  await page.goto("/meta-models");
  await expect(page.getByRole("heading", { level: 1, name: "Meta models in Accnomos" })).toBeVisible();
}

test.describe("desktop", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("signed out: the table lists each model, rows land on their sections, report links resolve", async ({ page }) => {
    await open(page);
    const table = page.getByRole("table", { name: "Meta models used in Accnomos" });
    await expect(table).toBeVisible();
    await expect(page.getByRole("list", { name: "Meta models used in Accnomos" })).toBeHidden();
    await expect(table.locator("tbody tr")).toHaveCount(MODELS.length);
    for (const [id, name] of MODELS) {
      const row = page.getByTestId(`row-${id}`);
      await expect(row.getByRole("rowheader")).toContainText(name);
      await expect(row.getByRole("link", { name, exact: true })).toHaveAttribute("href", `#${id}`);
      const section = page.getByTestId(`model-${id}`);
      await expect(section).toHaveAttribute("id", id);
      await expect(section.getByRole("heading", { level: 2, name, exact: true })).toBeVisible();
      for (const h of ["Jobs, and where you see them", "How it is called", "What code checks after it", "Measured"]) {
        await expect(section.getByRole("heading", { level: 3, name: h })).toBeVisible();
      }
    }

    // The live order (AI_PROVIDERS=meta,spark): Meta Model API first, the local fallback last; Modal only as optional.
    await expect(page.getByTestId("live-order")).toContainText("the Meta Model API (Muse Spark 1.3) answers first and a local fallback model answers last");
    await expect(page.getByTestId("live-order")).toContainText("Muse Spark 1.3 in Contributor mode for the demo and testing");
    await expect(page.getByTestId("live-order")).toContainText("Meta may use the content sent to it to improve its models");
    await expect(page.getByTestId("live-order")).toContainText("the server switches to standard mode");
    await expect(table.locator("tbody tr").first()).toContainText("Muse Spark");
    await expect(page.getByTestId("model-muse-spark")).toContainText("1st Muse Spark 1.3 on the Meta Model API (Contributor mode for the demo and testing); last, a local fallback model");
    await expect(page.getByTestId("model-muse-glimmer")).toContainText("optional extra provider");
    const modal = (await page.locator("main").innerText()).split("\n").filter((l) => /Modal/.test(l));
    for (const line of modal) expect(line, "Modal only as an optional provider").toMatch(/optional extra provider/);
    // Figures come from the committed runs at build time.
    await expect(page.getByTestId("row-muse-glimmer")).toContainText("clean documents 85 %; messy documents 80 %; CIS 92.5 %; property 89.8 %");
    await expect(page.getByTestId("row-muse-spark")).toContainText("Not measured yet");
    const glimmer = page.getByTestId("model-muse-glimmer");
    await expect(glimmer).toContainText("every figure exact 92.5 %"); // evals/runs/cis_read
    await expect(glimmer).toContainText("every figure exact 89.8 %"); // evals/runs/property_docs
    await expect(glimmer).toContainText("32/32 exact; 0 invented figures reached the user"); // evals/runs/ask_40
    await expect(page.getByTestId("model-muse-spark-open")).toContainText("every field right 91 %");
    await expect(page.getByTestId("model-muse-voice-transcribe")).toContainText(/Not measured yet|word error rate/);
    await expect(page.getByTestId("model-muse-voice-transcribe")).toContainText("a local fallback model");

    // Every report link is a file in this repository; every in-page link lands.
    const reports = page.locator(`main a[href^="${BLOB}"]`);
    expect(await reports.count()).toBeGreaterThan(8);
    for (const href of await reports.evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""))) {
      expect(existsSync(join(ROOT, href.slice(BLOB.length))), href).toBe(true);
    }
    for (const href of await page.locator('main a[href^="#"]').evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""))) {
      expect(await page.locator(href).count(), href).toBe(1);
    }

    expect(await page.locator("main").innerText()).not.toMatch(NOT_NAMED);
  });

  test("the public footer and /judges link to it", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("navigation", { name: "Help" }).getByRole("link", { name: "Meta models used" }).click();
    await expect(page).toHaveURL(/\/meta-models$/);
    await page.goto("/judges");
    await page.getByRole("link", { name: "Which Meta model does what" }).click();
    await expect(page).toHaveURL(/\/meta-models$/);
    await expect(page.getByTestId("row-muse-glimmer")).toBeVisible();
  });

  test("signed in: the Home summary's note and the app footer link to it", async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/");
    const summary = page.getByRole("region", { name: /^Your summary/ });
    await expect(summary.locator("[data-home-summary]")).toBeVisible();
    await summary.getByRole("link", { name: "Which Meta model does what" }).click();
    await expect(page).toHaveURL(/\/meta-models$/);
    await expect(page.getByRole("table", { name: "Meta models used in Accnomos" })).toBeVisible();
    expect(await page.locator("main").innerText()).not.toMatch(NOT_NAMED);
    await page.getByRole("navigation", { name: "About" }).getByRole("link", { name: "Meta models used" }).click();
    await expect(page).toHaveURL(/\/meta-models$/);
  });
});

test.describe("phone", () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test("360 px: stacked cards instead of the table, nothing wider than the screen", async ({ page }) => {
    await open(page);
    await expect(page.getByRole("table", { name: "Meta models used in Accnomos" })).toBeHidden();
    const cards = page.getByRole("list", { name: "Meta models used in Accnomos" });
    await expect(cards).toBeVisible();
    await expect(cards.getByRole("listitem")).toHaveCount(MODELS.length);
    for (const [id, name] of MODELS) await expect(page.getByTestId(`card-${id}`)).toContainText(name);
    const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
    expect(scroll).toBeLessThanOrEqual(width);
  });
});
