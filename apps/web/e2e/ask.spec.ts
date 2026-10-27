import { createBooksFolder, expect, pickVatPeriod, signIn, test } from "./fixtures";

test("ask about the picked VAT period → an answer with key numbers and the files it used", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // one purchase: £8.65 VAT reclaimed in Jul–Sep 2026

  // Ask follows the period picked on /vat (the current one, Oct–Dec, would be £0.00).
  await page.goto("/vat");
  await pickVatPeriod(page, "Jul–Sep 2026");
  await page.getByRole("link", { name: "Ask about Jul–Sep 2026" }).click();
  await expect(page).toHaveURL(/\/ask$/);

  const asks: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/books/ask")) asks.push(r.url());
  });
  await page.getByLabel("Ask your books").fill("How much VAT do I owe this quarter?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const answer = page.getByRole("article");
  await expect(answer).toContainText("Your net VAT (Box 5) for this quarter is £8.65");
  expect(asks).toHaveLength(1); // streamed (server-sent events), no fallback to the plain call
  expect(asks[0]).toContain("stream=1");
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
