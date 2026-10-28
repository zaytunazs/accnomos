import { createBooksFolder, expect, signIn, test } from "./fixtures";

// The month-end close agent (services/runtime/app/month_end.py) on the test runtime's fakes. Today is pinned to
// 27 Oct 2026; no business settings are saved, so the runtime assumes calendar quarters.

const events = (files: string[]) => files.filter((f) => f.startsWith("_System/Ledger/events/"));

test("a month with no bank statement: each step says what is missing, nothing is posted, no close offered", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd, 14 Aug 2026, paid by card
  const before = events(await runtime.files());

  await page.goto("/month-end?month=2026-08");
  await expect(page.getByRole("combobox", { name: "Month" })).toHaveValue("2026-08");
  await page.getByRole("button", { name: "Close August" }).click();

  const list = page.getByRole("list", { name: "Close checklist for August 2026" });
  const step = (n: number, title: string) => list.getByRole("listitem", { name: `Step ${n}: ${title}` });
  await expect(step(9, "Lock")).toContainText("Blocked", { timeout: 30_000 });
  await expect(step(1, "Inbox")).toContainText("OK");
  await expect(step(2, "Bank")).toContainText("No bank statements imported yet: upload August's statement (CSV) on Bank.");
  await expect(step(2, "Bank").getByRole("link", { name: "Open Bank" })).toHaveAttribute("href", "/bank");
  await expect(step(6, "VAT")).toContainText("August does not end a VAT period (Jul–Sep 2026 ends on 30 Sep 2026).");
  await expect(step(8, "Reports")).toContainText("Waiting for 1 blocking item above");
  await expect(step(9, "Lock")).toContainText("Clear the 1 blocking item above first");
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0); // no close card while something blocks

  const summary = page.getByRole("region", { name: "August 2026" });
  // The stub AI's words, which quote only the counts code gave it; code checked every figure.
  await expect(summary).toContainText("Test stub summary for August 2026: 1 to look at, 1 blocking the close.");
  await expect(summary).toContainText("every figure checked by code");

  const files = await runtime.files();
  expect(events(files)).toEqual(before); // the agent posts nothing
  expect(files).toContain("_System/close/2026-08.json");
  expect(files.some((f) => f.startsWith("07 Reports/"))).toBeFalsy();

  // The run is recorded: a reload shows it again, and Home's card counts what needs the user.
  await page.reload();
  await expect(step(2, "Bank")).toContainText("No bank statements imported yet");
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Month-end" })).toContainText("September has not been closed yet");
});

test("the sample books: September ends the VAT quarter, the boxes are shown and reminders wait for Approve", async ({ page, runtime }) => {
  test.slow(); // loads the whole sample seed first
  await signIn(page);
  await createBooksFolder(page);
  await runtime.api("POST", "/books/sample");
  await expect
    .poll(async () => (await runtime.api<{ state: string }>("GET", "/books/sample")).state, { timeout: 150_000, intervals: [2_000] })
    .toBe("done");
  const before = events(await runtime.files());
  const sent = (await runtime.sent()).length;

  await page.goto("/month-end?month=2026-09");
  await page.getByRole("button", { name: "Close September" }).click();
  const list = page.getByRole("list", { name: "Close checklist for September 2026" });
  const step = (n: number, title: string) => list.getByRole("listitem", { name: `Step ${n}: ${title}` });
  await expect(step(9, "Lock")).not.toContainText("Waiting", { timeout: 60_000 });

  const vat = step(6, "VAT");
  await expect(vat).toContainText("The return for Jul–Sep 2026 is ready to check");
  await expect(vat).toContainText("Accnomos never submits on its own");
  await expect(vat.getByRole("table", { name: "VAT return boxes, Jul–Sep 2026" }).getByRole("row")).toHaveCount(9);
  await expect(vat).toContainText(/Digital links: \d+ ledger entries on this return/);
  for (const [n, title] of [[1, "Inbox"], [2, "Bank"], [3, "Sales"], [4, "Purchases"], [5, "Payroll"], [7, "Checks"], [8, "Reports"]] as const) {
    await expect(step(n, title)).toContainText(/OK|Needs you|Blocked/);
  }
  await expect(page.getByRole("region", { name: "September 2026" })).toContainText("September 2026");

  // Reminders and bank matches are cards; nothing was sent or posted by the run.
  expect((await runtime.sent()).length).toBe(sent);
  const files = await runtime.files();
  expect(events(files)).toEqual(before);
  expect(files).toContain("_System/close/2026-09.json");
});
