import { createBooksFolder, DEMO_DAY, expect, pickVatPeriod, signIn, test } from "./fixtures";
import { RUNTIME_URL } from "./env.mjs";

test("ask about the picked VAT period → an answer with key numbers and the files it used", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // one purchase: £8.65 VAT reclaimed in Jul–Sep 2026

  // Ask follows the period picked on /vat (the current one, Oct–Dec, would be £0.00).
  await page.goto("/vat");
  await pickVatPeriod(page, "Jul–Sep 2026");
  await page.getByRole("link", { name: "Ask about Jul–Sep 2026" }).click();
  await expect(page).toHaveURL(/\/ask$/);

  await page.getByLabel("Ask your books").fill("How much VAT do I owe this quarter?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const answer = page.getByRole("article");
  await expect(answer).toContainText("Your net VAT (Box 5) for this quarter is £8.65");
  const keyNumbers = answer.getByRole("table", { name: "Key numbers" });
  await expect(keyNumbers.getByRole("row").filter({ hasText: "Net VAT (Box 5), 26A3" })).toContainText("£8.65"); // 26A3 = Jul–Sep
  await expect(keyNumbers.getByRole("row").filter({ hasText: "VAT reclaimed (Box 4)" })).toContainText("£8.65");
  await expect(answer.getByRole("list", { name: "Files used" })).toContainText("_System/Ledger/events/2026-08/");
  await expect(answer).toContainText("Numbers by code · explanation by accnomos-test-stub");
  await expect(answer).not.toContainText("These figures come straight from your ledger"); // not the fallback
});

test("“plan my Thursday” → a day-plan card around the calendar", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/ask");
  await page.getByLabel("Ask your books").fill("Plan my Thursday");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const answer = page.getByRole("article");
  await expect(answer).toContainText("I can plan Thursday 29 October");
  await answer.getByRole("link", { name: /^Plan Thursday/ }).click();

  // Home opens the plan for /?plan=2026-10-29; nothing is in the calendar until Apply.
  await expect(page).toHaveURL(/\/\?plan=2026-10-29$/);
  const plan = page.getByRole("article", { name: "Plan for Thursday 29 October" });
  await expect(plan).toBeVisible();
  const timeline = plan.getByRole("list", { name: "Timeline" });
  await expect(timeline.getByRole("listitem").filter({ hasText: "Site meeting, Harbour Lane kitchen" })).toContainText("09:00–10:00");
  await plan.getByRole("button", { name: "Discard" }).click();
  await expect(plan).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);
});

test("an instruction → action card; an approval that died halfway says what to do, and Reject clears it", async ({ page, runtime }) => {
  await runtime.reset("demo"); // JM Trading Ltd in the Outlook address book
  await signIn(page, DEMO_DAY);
  await createBooksFolder(page);
  await runtime.api("POST", "/contacts/import-outlook", { add_new: true });

  await page.goto("/ask");
  await page.getByLabel("Ask your books").fill("send a £100 invoice to JM Trading");
  const asked = page.waitForResponse((r) => r.url().startsWith(RUNTIME_URL) && new URL(r.url()).pathname === "/books/ask");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const action = ((await (await asked).json()) as { proposed_action: { id: string; kind: string; created_at: string } }).proposed_action;
  const card = page.getByRole("article", { name: "Proposed: Invoice" });
  await expect(card).toContainText("JM Trading Ltd · emailed to accounts@jmtrading.example");

  // The runtime died after writing `approving` 11 minutes ago (docs/ACTIONS.md, "Once only"): it is never run again.
  const ts = new Date(Date.now() - 11 * 60_000).toISOString().replace("Z", "+00:00");
  const line = { ts, action_id: action.id, kind: action.kind, event: "approving", user: "sam@sambuilds.example" };
  await runtime.putFile(`_System/audit/actions/${action.created_at.slice(0, 7)}.jsonl`, `${JSON.stringify(line)}\n`);

  await card.getByRole("button", { name: "Approve" }).click();
  const alert = card.getByRole("alert");
  await expect(alert).toContainText("The earlier approval of this action did not finish");
  await expect(alert).toContainText("give it 10 minutes, check Invoices, then press Reject and ask again if it is still needed.");
  await card.getByRole("button", { name: "Reject" }).click();
  await expect(card.getByRole("status")).toHaveText("Rejected. Nothing was done.");
  expect(await runtime.sent()).toEqual([]);
});
