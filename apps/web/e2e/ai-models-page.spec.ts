import { existsSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * /ai-models (src/app/ai-models/page.tsx, data in src/lib/ai-models-page.ts): one page saying which AI model
 * does which job. It lists every model in use, each overview row lands on its section, every report link points at a
 * file committed in this repository, and the page names no hardware, no vendor and no model product name. Reached from the
 * public footer, the app footer, /demo, /judges and the Home summary card.
 */
const MODELS = [
  ["hosted-model", "Hosted model"],
  ["local-model", "Local open-weights model"],
  ["verifier-model", "Open-weights verifier model"],
  ["speech-to-text", "Speech-to-text model"],
  ["receipt-crop", "Receipt-crop image model"],
  ["image-model", "Image-generation model"],
] as const;
const ROOT = join(process.cwd(), "..", "..");
const BLOB = "https://github.com/zaytunazs/accnomos/blob/main/";
const NOT_NAMED = /DGX|Ollama|vLLM|Whisper|Kokoro|Qwen|ComfyUI|Baseten|L40S|\bModal\b|NVIDIA|Claude|Anthropic|OpenAI|\bMeta\b|\bMuse\b|\bGlimmer\b|Segment Anything|SAM 3|coming soon|\bbeta\b|early access|launching/i;

async function open(page: Page) {
  await page.goto("/ai-models");
  await expect(page.getByRole("heading", { level: 1, name: "AI models in Accnomos" })).toBeVisible();
}

test.describe("desktop", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("signed out: the table lists each model, rows land on their sections, report links resolve", async ({ page }) => {
    await open(page);
    const table = page.getByRole("table", { name: "AI models used in Accnomos" });
    await expect(table).toBeVisible();
    await expect(page.getByRole("list", { name: "AI models used in Accnomos" })).toBeHidden();
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

    // The live order since 11 Nov 2026 (AI_PROVIDERS=spark,anthropic): our own server first, a backup provider last;
    // before that the hosted model first. The hosted GPU only as optional.
    await expect(page.getByTestId("live-order")).toContainText("the local open-weights model on our own server answers first since 11 November 2026");
    await expect(page.getByTestId("live-order")).toContainText("the hosted model in Contributor mode for the demo and testing");
    await expect(page.getByTestId("live-order")).toContainText("the model's provider may use the content sent to it to improve its models");
    await expect(page.getByTestId("live-order")).toContainText("Since 11 November 2026 our server sends nothing to the hosted model");
    await expect(table.locator("tbody tr").first()).toContainText("Hosted model");
    await expect(page.getByTestId("model-hosted-model")).toContainText("1st the local open-weights model on our own server; last, a backup AI provider");
    await expect(page.getByTestId("model-local-model")).toContainText("optional extra provider");
    const modal = (await page.locator("main").innerText()).split("\n").filter((l) => /hosted GPU/.test(l));
    for (const line of modal) expect(line, "the hosted GPU only as an optional provider").toMatch(/optional extra provider/);
    // Figures come from the committed runs at build time.
    await expect(page.getByTestId("row-local-model")).toContainText("clean documents 85 %; messy documents 80 %; CIS 92.5 %; property 99.1 %");
    await expect(page.getByTestId("row-hosted-model")).toContainText(/document type \d+(\.\d)? %/); // evals/runs/classify
    await expect(page.getByTestId("model-hosted-model")).toContainText("Every other job");
    // The hosted model measured live on 200 documents (evals/runs/spark13_200, spark13_messy_200) and run live on our server
    await expect(page.getByTestId("row-hosted-model")).toContainText("clean documents 95 %; messy documents 96 %");
    await expect(page.getByTestId("model-hosted-model")).toContainText("Run live on our server");
    await expect(page.getByTestId("model-hosted-model")).not.toContainText("faked HTTP");
    await expect(page.getByTestId("model-speech-to-text")).toContainText("Used from the Android app on a real phone");
    // The crop model run live (evals/runs/sam_crop_live), with the code crop's earlier figure kept as the fallback's
    const sam = page.getByTestId("model-receipt-crop");
    await expect(sam).toContainText("Crop, live on the hosted model's API");
    await expect(sam).toContainText(/a box for \d+ of 20 photos; mean overlap 0\.\d+ against 0\.88 for the plain-code crop/);
    await expect(sam).not.toContainText("never run live");
    await expect(page.getByTestId("row-receipt-crop")).toContainText(/crop overlap 0\.\d+/);
    await expect(page.getByTestId("model-local-model")).toContainText(/right account \d+(\.\d)? %/); // evals/runs/bank_ai
    const glimmer = page.getByTestId("model-local-model");
    await expect(glimmer).toContainText("every figure exact 92.5 %"); // evals/runs/cis_read
    await expect(glimmer).toContainText("every figure exact 99.1 %"); // evals/runs/property_docs
    await expect(glimmer).toContainText("32/32 exact; 0 invented figures reached the user"); // evals/runs/ask_40
    await expect(page.getByTestId("model-verifier-model")).toContainText("every field right 91 %");
    await expect(page.getByTestId("model-speech-to-text")).toContainText(/word error rate \d+(\.\d)? %/); // evals/runs/stt
    await expect(page.getByTestId("model-speech-to-text")).toContainText("a local fallback model");

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

  test("the public footer, /demo and /judges link to it", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("navigation", { name: "Help" }).getByRole("link", { name: "AI models used" }).click();
    await expect(page).toHaveURL(/\/ai-models$/);
    for (const route of ["/demo", "/judges"]) {
      await page.goto(route);
      await page.getByRole("link", { name: "Which AI model does what" }).click();
      await expect(page).toHaveURL(/\/ai-models$/);
      await expect(page.getByTestId("row-local-model")).toBeVisible();
    }
  });

  test("signed in: the Home summary's note and the app footer link to it", async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/");
    const summary = page.getByRole("region", { name: /^Your summary/ });
    await expect(summary.locator("[data-home-summary]")).toBeVisible();
    await summary.getByRole("link", { name: "Which AI model does what" }).click();
    await expect(page).toHaveURL(/\/ai-models$/);
    await expect(page.getByRole("table", { name: "AI models used in Accnomos" })).toBeVisible();
    expect(await page.locator("main").innerText()).not.toMatch(NOT_NAMED);
    await page.getByRole("navigation", { name: "About" }).getByRole("link", { name: "AI models used" }).click();
    await expect(page).toHaveURL(/\/ai-models$/);
  });
});

test.describe("phone", () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test("360 px: stacked cards instead of the table, nothing wider than the screen", async ({ page }) => {
    await open(page);
    await expect(page.getByRole("table", { name: "AI models used in Accnomos" })).toBeHidden();
    const cards = page.getByRole("list", { name: "AI models used in Accnomos" });
    await expect(cards).toBeVisible();
    await expect(cards.getByRole("listitem")).toHaveCount(MODELS.length);
    for (const [id, name] of MODELS) await expect(page.getByTestId(`card-${id}`)).toContainText(name);
    const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
    expect(scroll).toBeLessThanOrEqual(width);
  });
});
