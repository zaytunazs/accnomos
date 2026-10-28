import { readFile } from "node:fs/promises";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

const FILING =
  "File with HMRC's Basic PAYE Tools or your payroll provider. Direct submission from Accnomos is currently not available.";

test("PAYE payroll: settings → employee → pay run → approve → FPS, EPS, pension file, payslip and report", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/payroll");

  // The filing reminder is at the top, and RTI submission is a switch that cannot be turned on.
  await expect(page.getByRole("note", { name: "Filing" })).toContainText(FILING);
  await expect(page.getByRole("note", { name: "Filing" })).toContainText("Estimate — check before filing");
  await expect(page.getByLabel("Submit RTI to HMRC from Accnomos (not available)")).toBeDisabled();

  const settings = page.getByRole("form", { name: "Payroll settings" });
  await settings.getByLabel("Employer name").fill("Sam Builds Ltd");
  await settings.getByLabel("HMRC office number").fill("123");
  await settings.getByLabel("PAYE reference").fill("AB45678");
  await settings.getByLabel("Accounts Office reference").fill("123PA00045678");
  await settings.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("status")).toHaveText("Payroll settings saved.");

  await page.getByRole("button", { name: "Add employee" }).click();
  const form = page.getByRole("form", { name: "New employee" });
  await form.getByLabel("Payroll ID").fill("E001");
  await form.getByLabel("Forenames").fill("Ann");
  await form.getByLabel("Surname").fill("Lee");
  await form.getByLabel("NI number").fill("AB123456C");
  await form.getByLabel("Date of birth").fill("1990-05-01");
  await form.getByLabel("Address line 1").fill("1 High Street");
  await form.getByLabel("Address line 2").fill("London");
  await form.getByLabel("Postcode").fill("SW16 1AA");
  await form.getByLabel("Start date").fill("2020-01-06");
  await form.getByLabel("Starter declaration").selectOption("");
  await form.getByLabel("Tax code").fill("1257L");
  await form.getByLabel("Annual salary £").fill("36000");
  await form.getByRole("button", { name: "Save employee" }).click();
  await expect(page.getByRole("status")).toHaveText("Ann Lee saved.");

  await page.getByLabel("Pay date").first().fill("2026-10-31");
  await page.getByRole("button", { name: "Calculate pay run" }).click();
  await expect(page.getByRole("status")).toHaveText("Pay run 2026-27-monthly-07 calculated.");
  const run = page.getByRole("region", { name: "Pay run 2026-27-monthly-07" });
  const ann = run.getByRole("row", { name: /Ann Lee/ });
  // £3,000 a month; tax 0 (month 7 cumulative free pay), employee NI (3,000 - 1,048) x 8%, employer (3,000 - 417) x 15%.
  await expect(ann.getByRole("cell").nth(0)).toHaveText("£3,000.00");
  await expect(ann.getByRole("cell").nth(2)).toHaveText("£156.16");
  await expect(ann.getByRole("cell").nth(6)).toHaveText("£387.45");
  await expect(run).toContainText("Estimate — check before filing");
  await expect(page.getByRole("button", { name: "Download FPS for 2026-27-monthly-07" })).toBeDisabled();

  await run.getByRole("button", { name: "Send to Review" }).click();
  await expect(page.getByRole("status")).toHaveText("Sent to Review. Nothing is posted until you approve it.");
  page.once("dialog", (d) => d.accept());
  await run.getByRole("button", { name: "Approve and post" }).click();
  await expect(page.getByRole("status")).toHaveText("Pay run approved and posted to your books.");
  await expect(run).toContainText("Approved and posted");

  // FPS: the file, its readable contents, and the filing note beside the button.
  const rti = page.getByRole("region", { name: "RTI files (FPS and EPS)" });
  await expect(rti.getByRole("note")).toHaveText(FILING);
  const [fps] = await Promise.all([page.waitForEvent("download"), rti.getByRole("button", { name: "Download FPS for 2026-27-monthly-07" }).click()]);
  expect(fps.suggestedFilename()).toBe("FPS-2026-27-monthly-07.xml");
  const xml = await readFile((await fps.path())!, "utf-8");
  expect(xml).toContain("http://www.govtalk.gov.uk/taxation/PAYE/RTI/FullPaymentSubmission/26-27/1");
  expect(xml).toContain("<NINO>AB123456C</NINO>");
  // The notice travels inside the file too.
  expect(xml).toContain("<!-- NOT SUBMITTED TO HMRC.");
  expect(xml).toContain("must be filed using HMRC's Basic PAYE Tools");
  await expect(page.getByRole("status")).toContainText(FILING);
  await expect(rti.getByRole("table", { name: /Full Payment Submission contents/ })).toContainText("1257L");

  await rti.getByLabel("Claim Employment Allowance on this EPS").check();
  const [eps] = await Promise.all([page.waitForEvent("download"), rti.getByRole("button", { name: "Download EPS" }).click()]);
  expect(eps.suggestedFilename()).toBe("EPS-2026-27-month-07.xml");
  expect(await readFile((await eps.path())!, "utf-8")).toContain("<EmpAllceInd>yes</EmpAllceInd>");

  const pension = page.getByRole("region", { name: "Pension contribution schedule" });
  const [nest] = await Promise.all([page.waitForEvent("download"), pension.getByRole("button", { name: "Nest CSV" }).click()]);
  expect(nest.suggestedFilename()).toBe("pension-nest-2026-27-monthly-07.csv");
  expect(await readFile((await nest.path())!, "utf-8")).toMatch(/^H,/);
  // Smart Pension's PAPDIS upload is for the net pay arrangement only; this scheme is relief at source.
  await pension.getByRole("button", { name: "Smart Pension (PAPDIS) CSV" }).click();
  await expect(page.getByText(/net pay arrangement only/).first()).toBeVisible();

  const [slip] = await Promise.all([page.waitForEvent("download"), run.getByRole("button", { name: "Payslip for Ann Lee" }).click()]);
  expect(slip.suggestedFilename()).toBe("payslip-2026-27-monthly-07-E001.pdf");

  const reports = page.getByRole("region", { name: "Payroll reports" });
  await reports.getByLabel("Report").selectOption("p32");
  await reports.getByRole("button", { name: "Show" }).click();
  await expect(reports.getByRole("table", { name: "Employer payment record (P32-style)" })).toContainText("2026-11-22");
  const [xlsx] = await Promise.all([page.waitForEvent("download"), reports.getByRole("button", { name: "XLSX" }).click()]);
  expect(xlsx.suggestedFilename()).toBe("p32.xlsx");
});

test("a starter-code suggestion that arrives late never overwrites the tax code typed meanwhile", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/payroll");
  // Hold the suggestion until the tax code has been typed (the race the long flow above used to lose on slow runners).
  let release!: () => void;
  const typed = new Promise<void>((r) => (release = r));
  await page.route("**/payroll/paye/starter-code*", async (route) => {
    await typed;
    await route.continue();
  });
  const reply = page.waitForResponse("**/payroll/paye/starter-code*");

  await page.getByRole("button", { name: "Add employee" }).click();
  const form = page.getByRole("form", { name: "New employee" });
  await form.getByLabel("Starter declaration").selectOption("");
  await expect(form.getByLabel("Starter declaration")).toHaveValue("");
  await form.getByLabel("Tax code").fill("1257L");
  release();
  await reply;
  await expect(form.getByLabel("Tax code")).toHaveValue("1257L");
  await expect(form.getByLabel("Starter declaration")).toHaveValue("");
});
