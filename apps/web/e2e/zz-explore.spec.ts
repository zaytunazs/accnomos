// TEMPORARY exploration (not committed): dump every page's aria snapshot, console errors and failed requests.
import { writeFileSync, mkdirSync } from "node:fs";
import { createBooksFolder, signIn, test } from "./fixtures";

const PAGES = ["/", "/review", "/ask", "/invoices", "/invoices/new", "/bank", "/vat", "/jobs", "/jobs/job", "/payroll", "/contacts", "/vehicles", "/files", "/settings"];

test("explore", async ({ page, runtime }) => {
  test.setTimeout(240_000);
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();
  mkdirSync("/tmp/explore", { recursive: true });
  for (const path of PAGES) {
    const log: string[] = [];
    page.removeAllListeners("console");
    page.removeAllListeners("pageerror");
    page.removeAllListeners("response");
    page.on("console", (m) => (m.type() === "error" || m.type() === "warning") && log.push(`console.${m.type()}: ${m.text()}`));
    page.on("pageerror", (e) => log.push(`pageerror: ${e.message}`));
    page.on("response", (r) => r.status() >= 400 && log.push(`HTTP ${r.status()} ${r.request().method()} ${r.url()}`));
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    const snap = await page.locator("main").first().ariaSnapshot();
    writeFileSync(`/tmp/explore/${path.replace(/\//g, "_") || "_root"}.txt`, `${log.join("\n")}\n----\n${snap}\n`);
  }
});
