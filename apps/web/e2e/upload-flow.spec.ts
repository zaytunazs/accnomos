import { readFileSync } from "node:fs";
import { join } from "node:path";
import { confirmScan, createBooksFolder, expect, GOLD, settingsTab, signIn, test } from "./fixtures";

// Upload → progress → the AI's guess of the type, confirmed by the user → routed (services/runtime/app/scan_jobs.py,
// src/components/review/ScanProgress.tsx). No Scan press, and no request that waits on the model.

const BARCLAYS = readFileSync(join(__dirname, "../../../evals/gold/bank/barclays.csv"));
const row = (page: import("@playwright/test").Page, name: string) => page.locator(`[data-scan-file="${name}"]`);
const status = (page: import("@playwright/test").Page) => page.locator('p[role="status"][aria-live="polite"]');

test("upload a receipt and a bank CSV: reading starts by itself, each type is confirmed, then routed", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/review");
  const starts: string[] = [];
  page.on("request", (r) => r.url().includes("/books/scan") && r.method() === "POST" && starts.push(new URL(r.url()).pathname));

  await page.locator('input[type="file"]').first().setInputFiles([
    { name: "currys.png", mimeType: "image/png", buffer: await runtime.goldPng() },
    { name: "statement.csv", mimeType: "text/csv", buffer: BARCLAYS },
  ]);
  await expect(page.getByText("2 files added to 00 Inbox. Reading now")).toBeVisible();
  expect(starts).toEqual(["/books/scan/jobs"]); // one short call; no blocking /books/scan

  await expect(row(page, "currys.png")).toHaveAttribute("data-stage", "confirm", { timeout: 30_000 });
  await expect(row(page, "statement.csv")).toHaveAttribute("data-stage", "confirm");
  await expect(row(page, "currys.png")).toContainText("Looks like a receipt (90% sure)");
  await expect(row(page, "statement.csv")).toContainText("Looks like a bank statement (95% sure, guessed by code)");
  await expect(page.getByRole("progressbar", { name: "Overall progress" })).toHaveAttribute("aria-valuenow", "50");
  await expect(page.locator("[data-scan-badge]")).toHaveText("2 to confirm");
  // Nothing is read in full, filed or proposed before the user says what each file is.
  expect((await runtime.files()).filter((f) => f.startsWith("00 Inbox/")).sort()).toEqual(["00 Inbox/currys.png", "00 Inbox/statement.csv"]);
  await expect(page.getByRole("heading", { name: /Nothing waiting|No receipts waiting/ }).first()).toBeVisible();

  await page.getByRole("button", { name: "Confirm all 2" }).click();
  await expect(row(page, "currys.png")).toHaveAttribute("data-stage", "ready", { timeout: 30_000 });
  await expect(row(page, "statement.csv")).toHaveAttribute("data-stage", "ready");
  await expect(row(page, "statement.csv")).toContainText("new bank lines: match them on Bank.");
  await expect(row(page, "statement.csv").getByRole("link", { name: "Match the lines on Bank" })).toBeVisible();
  await expect(status(page)).toHaveText("1 new proposal");
  await expect(page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" })).toBeVisible();
  await expect(page.locator("[data-scan-badge]")).toHaveCount(0);
  await expect(page.getByText(/^Done · 2 ready to review/)).toBeVisible();
  const lines = await runtime.api<unknown[]>("GET", "/books/bank/lines");
  expect(lines.length).toBeGreaterThan(0);
});

test("change the AI's guess: a sales invoice confirmed as a payslip goes to Needs a look, saying why", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/review");
  await page.locator('input[type="file"]').first().setInputFiles({
    name: "march-pay.png",
    mimeType: "image/png",
    buffer: await runtime.goldPng("052_sales_invoice"),
  });
  await expect(row(page, "march-pay.png")).toContainText("Looks like a sales invoice (90% sure)", { timeout: 30_000 });
  await confirmScan(page, { name: "march-pay.png", kind: "payslip" });
  await expect(row(page, "march-pay.png")).toHaveAttribute("data-stage", "needs_a_look");
  await expect(row(page, "march-pay.png")).toContainText("Payslips are not posted from Review: run pay in Payroll");
  await expect(status(page)).toHaveText("1 new proposal");
  const flagged = await runtime.api<{ checks: { code: string }[] }[]>("GET", "/books/proposals?status=needs_a_look");
  expect(flagged.map((p) => p.checks.map((c) => c.code))).toEqual([["DOC_KIND"]]);
});

test("the reading carries on when you leave the page; the top bar shows the count and Review shows the rest", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/review");
  await page.locator('input[type="file"]').first().setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
  await expect(page.getByText("1 file added to 00 Inbox. Reading now")).toBeVisible();
  await page.goto("/"); // leave at once
  const badge = page.locator("[data-scan-badge]");
  await expect(badge).toHaveText(/^(Reading 1|1 to confirm)$/);
  await expect(badge).toHaveText("1 to confirm", { timeout: 30_000 });
  await badge.click();
  await expect(page).toHaveURL(/\/review$/);
  await confirmScan(page, { name: `${GOLD}.png` });
  await expect(page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" })).toBeVisible();
});

test("Outlook intake: a real check starts the same reading, with types to confirm on Review", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/settings");
  const intake = (await settingsTab(page, "Automation")).getByRole("region", { name: "Outlook intake" });
  await intake.getByRole("switch", { name: "Outlook intake" }).click();
  await intake.getByRole("button", { name: "Check my inbox now" }).click();
  await expect(intake.getByRole("status")).toContainText("3 files imported");
  await expect(intake).toContainText("Reading them now: confirm each one’s type on Review.");
  await expect(page.locator("[data-scan-badge]")).toHaveText("3 to confirm", { timeout: 30_000 });
  await page.goto("/review");
  const waiting = page.locator('[data-scan-file][data-stage="confirm"]');
  await expect(waiting).toHaveCount(3);
  await expect(page.getByText("From your email · it carries on if you leave this page")).toBeVisible();
  await page.getByRole("button", { name: "Confirm all 3" }).click();
  await expect(page.getByText(/^Done · /)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("3 waiting for you")).toBeVisible();
  expect((await runtime.files()).filter((f) => f.startsWith("00 Inbox/"))).toEqual([]);
});
