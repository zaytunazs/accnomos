import { readFile } from "node:fs/promises";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("prepare a pay run from timesheets → export CSV → confirm and post", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.addHours(6, "2026-10-20"); // Alex Carter, £25/h cost: £150 gross for October

  await page.goto("/payroll");
  await expect(page.getByLabel("Month")).toHaveValue("2026-10");
  await expect(page.getByText("set in Settings › Business › Staff")).toBeVisible();
  await page.getByRole("button", { name: "Prepare October 2026 pay run" }).click();
  await expect(page.getByRole("status")).toHaveText("Pay run for October 2026 prepared from timesheets.");

  const run = page.getByRole("region", { name: /October 2026 pay run/ });
  await expect(run).toContainText("Draft");
  const alex = run.getByRole("row", { name: /Alex Carter/ });
  await expect(alex.getByLabel("Hours for Alex Carter")).toHaveValue("6");
  await expect(alex.getByLabel("Hourly rate for Alex Carter")).toHaveValue("25.00");
  await expect(alex.getByRole("cell").nth(2)).toHaveText("£150.00"); // gross: hours × rate

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export CSV" }).click()]);
  expect(download.suggestedFilename()).toBe("payroll-2026-10.csv");
  const csv = await readFile((await download.path())!, "utf-8");
  expect(csv).toContain("Alex Carter");
  expect(csv).toContain("150.00");
  await expect(page.getByRole("status")).toContainText("in your OneDrive and downloaded");
  expect((await runtime.files()).some((f) => f.includes("payroll") && f.endsWith(".csv"))).toBeTruthy();

  const confirm = page.getByRole("region", { name: "Confirm what was actually paid" });
  await confirm.getByLabel("Actual gross pay £ (provider)").fill("150.00");
  await confirm.getByLabel("Actual employer NI £ (provider)").fill("0");
  page.once("dialog", (d) => {
    expect(d.message()).toBe("Post £150.00 gross wages and £0.00 employer NI to your books for October 2026?");
    return d.accept();
  });
  await confirm.getByRole("button", { name: "Confirm and post" }).click();
  await expect(page.getByRole("status")).toHaveText("October 2026 staff costs posted to your books.");
  const posted = page.getByRole("region", { name: "Posted to your books" });
  await expect(posted).toContainText("Actual gross pay£150.00");
  await expect(run).toContainText("Confirmed and posted");
});
