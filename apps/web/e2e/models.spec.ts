import { createBooksFolder, expect, GOLD, settingsTab, signIn, test } from "./fixtures";

/**
 * "Meta models at work": the /models page and the Review card's line, with the runtime's provider chain
 * (AI_PROVIDERS=modal,meta,spark in playwright.config.ts; in test mode each provider is the stub AI).
 */

test("/models shows the chain in order, each provider's health and the eval headlines", async ({ page }) => {
  await page.goto("/models");
  await expect(page.getByRole("heading", { level: 1, name: "Meta models at work" })).toBeVisible();
  const chain = page.getByRole("list", { name: "Provider chain" });
  await expect(chain.getByRole("listitem")).toHaveCount(3);
  await expect(chain.getByRole("listitem").nth(0)).toContainText("1st");
  await expect(chain.getByTestId("provider-modal")).toContainText("Modal");
  await expect(chain.getByTestId("provider-meta")).toContainText("Meta Model API");
  await expect(chain.getByTestId("provider-spark")).toContainText("DGX Spark");
  await expect(chain.getByTestId("provider-modal")).toContainText("Warm"); // test mode probes the stub
  await expect(chain.getByTestId("provider-spark")).toContainText("Up");
  await expect(chain.getByTestId("provider-meta")).toContainText("Voice: no"); // the stub has no Muse Voice
  const report = page.getByRole("link", { name: "Report: evals/runs/spark_open_200" });
  await expect(report).toHaveAttribute("href", "https://github.com/zaytunazs/accnomos/blob/main/evals/runs/spark_open_200/report.md");
  await expect(page.getByRole("listitem").filter({ has: report })).toContainText("91 %"); // from summary.json at build
  await expect(page.getByRole("link", { name: "Report: evals/runs/autopilot_l2" })).toBeVisible();
});

test("signed in on the server's chain: the Review card names the Meta model and provider, and /models lists the calls", async ({ page, runtime }) => {
  await signIn(page);
  await page.addInitScript(() => window.localStorage.removeItem("accnomos.ai")); // no AI chosen: the server's chain
  await createBooksFolder(page);
  await page.goto("/review");
  await page.locator('input[type="file"]').first().setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
  await expect(page.getByText("1 file added to 00 Inbox")).toBeVisible();
  await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
  const novex = page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" });
  await expect(novex).toBeVisible();
  const line = novex.getByTestId("served-by");
  await expect(line).toContainText(/^Read by Test stub \(Modal\) · \d+\.\d s · checked by Test stub \(Modal\)/);
  await expect(novex).toContainText("Verifier agrees");

  await line.getByRole("link", { name: "Meta models at work" }).click();
  await expect(page).toHaveURL(/\/models$/);
  const calls = page.getByRole("table", { name: "Recent AI calls" });
  // The log is the whole runtime's (other workers chose the stub directly), so look for this chain's rows.
  for (const task of ["Read a document", "Second reading"]) {
    await expect(calls.getByRole("row").filter({ hasText: task }).filter({ hasText: "Test stub (Modal)" }).first()).toBeVisible();
  }
});

test("Settings and the footer link to /models", async ({ page }) => {
  await page.goto("/settings");
  const ai = await settingsTab(page, "AI");
  await expect(ai.getByRole("link", { name: "See the Meta models at work" })).toHaveAttribute("href", "/models");
  await expect(page.getByRole("navigation", { name: "About" }).getByRole("link", { name: "Meta models at work" })).toHaveAttribute("href", "/models");
});
