import { readFile } from "node:fs/promises";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("three actions in the books show on /audit with who did them; filters and CSV export work", async ({ page, runtime }) => {
  test.slow(); // three real actions plus a CSV download: runs past 30 s when the full suite loads the machine
  await signIn(page);
  await createBooksFolder(page);

  // 1 and 2: through the app, as the user.
  await page.goto("/vehicles");
  const vehicles = page.getByRole("region", { name: "Vehicles" });
  await vehicles.getByLabel("Name").fill("Ford Transit");
  await vehicles.getByRole("button", { name: "Add vehicle" }).click();
  await expect(page.getByRole("status")).toHaveText("Added Ford Transit");
  const log = page.getByRole("region", { name: "Mileage log" });
  await log.getByLabel("From").fill("Bristol");
  await log.getByLabel("To").fill("Bath");
  await log.getByLabel("Miles").fill("100");
  await log.getByLabel("Purpose").fill("Quote for kitchen, Harbour Lane");
  await log.getByRole("button", { name: "Add journey" }).click();
  await expect(page.getByRole("status")).toHaveText("Logged 100 miles");
  // 3: a receipt read by the reader agent and approved by the user.
  await runtime.postGold();

  // Settings' audit link leads here.
  await page.goto("/settings");
  await page.getByRole("link", { name: "Open the audit trail" }).click();
  await expect(page).toHaveURL(/\/audit$/, { timeout: 15_000 });

  // Test mode pins the runtime's "today", but audit lines carry the real clock: widen To to the real date.
  const real = new Date().toISOString().slice(0, 10);
  await page.getByLabel("To", { exact: true }).fill(real > "2026-10-27" ? real : "2026-10-27");

  const trail = page.getByRole("list", { name: "Audit trail" });
  const row = (text: string | RegExp) => trail.locator("li[data-event]").filter({ hasText: text });
  // The range change refetches the whole trail; under a loaded full run that takes longer than the default 5 s.
  await expect(row("Added a vehicle")).toContainText("You", { timeout: 20_000 });
  await expect(row("Logged a journey: 100 miles")).toContainText("You");
  await expect(row("Posted Novex Office Supplies Ltd £51.90 to the ledger")).toContainText("You");
  await expect(row("Read Novex Office Supplies Ltd £51.90 and proposed an entry")).toContainText("Reader");
  await expect(row("Posted Novex Office Supplies Ltd").getByRole("link", { name: "Review card" })).toHaveAttribute(
    "href",
    /^\/review#proposal-/,
  );
  // Nothing on the page edits a line.
  await expect(trail.getByRole("button")).toHaveCount(0);
  await expect(trail.getByRole("textbox")).toHaveCount(0);

  // Filters: You hides the reader's line; Autopilot did nothing today.
  const who = page.getByRole("radiogroup", { name: "Who did it" });
  await who.getByRole("radio", { name: "You" }).click();
  await expect(row("Added a vehicle")).toBeVisible();
  await expect(trail.getByText(/^Read Novex/)).toHaveCount(0);
  await who.getByRole("radio", { name: "Autopilot" }).click();
  await expect(page.getByText("Nothing in this range")).toBeVisible();
  await who.getByRole("radio", { name: "Everyone" }).click();
  await page.getByLabel("What").selectOption({ label: "Mileage" });
  await expect(row("Logged a journey")).toBeVisible();
  await expect(trail.getByText("Added a vehicle")).toHaveCount(0);
  await page.getByLabel("What").selectOption({ label: "Everything" });

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^accnomos-audit-\d{4}-\d{2}-\d{2}\.csv$/);
  const csv = await readFile((await file.path())!, "utf8");
  expect(csv).not.toContain("SAMPLE");
  expect(csv).toContain("ts,actor,actor_kind,who,event,summary");
  expect(csv).toContain("user:sam@sambuilds.example,user,You,vehicle_added,Added a vehicle");
  expect(csv).toContain("agent:extractor,agent,Reader,proposed");
});

test("signed out: a labelled sample day", async ({ page }) => {
  await page.goto("/audit");
  await expect(page.getByText(/Sample day at a fictional company: Wednesday,? 14 October 2026/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Wednesday,? 14 October 2026$/ })).toBeVisible();
  await page.getByRole("radiogroup", { name: "Who did it" }).getByRole("radio", { name: "Autopilot" }).click();
  const rows = page.getByRole("list", { name: "Audit trail" }).locator("li[data-event]");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("Posted Travis Perkins £212.40 to the ledger");
});
