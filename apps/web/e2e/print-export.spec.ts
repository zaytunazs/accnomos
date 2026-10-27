import { readFile } from "node:fs/promises";
import { expect, test } from "./fixtures";
import { csvCell, csvFilename, csvRows, csvText, SAMPLE_LABEL } from "../src/lib/csv";

test("csv.ts: RFC 4180 quoting, the formula guard, BOM, sample line and file names", async () => {
  expect(csvCell("plain")).toBe("plain");
  expect(csvCell("Acme, Kitchens")).toBe('"Acme, Kitchens"');
  expect(csvCell('She said "hi"')).toBe('"She said ""hi"""');
  expect(csvCell("line one\nline two")).toBe('"line one\nline two"');
  expect(csvCell(15000)).toBe("15000");
  expect(csvCell(null)).toBe("");
  expect(csvCell(undefined)).toBe("");

  for (const risky of ["=SUM(A1:A2)", "+44117", "-2+3", "@mention"]) {
    expect(csvCell(risky)).toBe(`'${risky}`);
  }
  expect(csvCell("2 - 1 = 1")).toBe("2 - 1 = 1"); // only a leading trigger counts

  expect(csvRows([["a", "b"], ["c", "d"]])).toBe("a,b\r\nc,d");

  const live = csvText([["number", "total_pence"], ["INV-0001", 32400]]);
  expect(live.charCodeAt(0)).toBe(0xfeff); // the BOM, so Excel opens it cleanly
  expect(live).toBe("\uFEFFnumber,total_pence\r\nINV-0001,32400\r\n");

  const sample = csvText([["number"]], { sample: true });
  expect(sample.startsWith(`\uFEFF${SAMPLE_LABEL}\r\n`)).toBe(true); // signed out: sample first line

  expect(csvFilename("invoices", new Date(2026, 9, 27))).toBe("accnomos-invoices-2026-10-27.csv");
  expect(csvFilename("bank")).toMatch(/^accnomos-bank-\d{4}-\d{2}-\d{2}\.csv$/);
});

test("signed out: the sample invoice list exports (download event, header row, BOM)", async ({ page }) => {
  await page.goto("/invoices");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export CSV" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^accnomos-invoices-\d{4}-\d{2}-\d{2}\.csv$/);
  const raw = await readFile((await download.path())!, "utf-8");
  expect(raw.charCodeAt(0)).toBe(0xfeff);
  const lines = raw.replace(/^\uFEFF/, "").split("\r\n");
  expect(lines[0]).toBe(SAMPLE_LABEL);
  expect(lines[1]).toBe("number,customer,issue_date,due_date,status,net_pence,vat_pence,total_pence");
  expect(raw).toContain("INV-0007");
});

test("print: the invoice list prints without chrome or controls", async ({ page }) => {
  await page.goto("/invoices");
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
  await expect(page.getByRole("navigation", { name: "Sections" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Print" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Export CSV" })).toBeHidden();
  await expect(page.getByText("INV-0007 · Harrogate Dental Ltd")).toBeVisible();
});
