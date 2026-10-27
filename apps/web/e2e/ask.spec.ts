import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("ask a question → an answer with the key numbers from the books", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // one purchase: £8.65 VAT reclaimed in Jul–Sep 2026

  await page.goto("/ask");
  await page.getByLabel("Ask your books").fill("How much VAT do I owe this quarter?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const answer = page.getByRole("article");
  await expect(answer).toContainText("Your net VAT (Box 5) for this quarter is £8.65");
  const keyNumbers = answer.getByRole("list", { name: "Key numbers" });
  await expect(keyNumbers.getByRole("listitem").filter({ hasText: "Net VAT (Box 5), 26A3" })).toContainText("£8.65");
  await expect(keyNumbers.getByRole("listitem").filter({ hasText: "VAT reclaimed (Box 4)" })).toContainText("£8.65");
  await expect(answer).toContainText("words by accnomos-test-stub");
  await expect(answer).not.toContainText("These figures come straight from your ledger"); // not the fallback
});
