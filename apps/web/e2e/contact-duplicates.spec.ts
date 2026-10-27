import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("contacts: possible duplicates, merge, undo, not the same", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd
  await runtime.postGold("002_mixed"); // Marrs & Ockway Provisions Ltd
  await runtime.api("POST", "/contacts/refresh");

  // Arrange the duplicate: the same phone number on both contacts (and no VAT numbers, so code
  // does not rule the group out as two businesses).
  const before: { contacts: { id: string }[] } = await runtime.api("GET", "/contacts");
  expect(before.contacts).toHaveLength(2);
  for (const c of before.contacts) {
    await runtime.api("PUT", `/contacts/${c.id}`, { phone: "0117 496 0123", vrn: null });
  }

  // The runtime's own view: one group, code evidence plus the stub model's view.
  const dups: { groups: { ai: { same: boolean } | null; evidence: string[] }[] } =
    await runtime.api("GET", "/contacts/duplicates");
  expect(dups.groups).toHaveLength(1);
  expect(dups.groups[0].evidence).toContain("same phone 01174960123");
  expect(dups.groups[0].ai?.same).toBe(true); // the test-mode stub, not a real model

  await page.goto("/contacts");
  const card = page.getByLabel("Possible duplicates");
  await expect(card.getByRole("heading", { name: "Possible duplicates (1)" })).toBeVisible();
  await expect(card).toContainText("same phone 01174960123");
  await expect(card).toContainText("AI view: same business");

  await card.getByRole("button", { name: "Merge" }).click();
  await card.getByRole("button", { name: "Confirm merge" }).click();
  await expect(card.getByText("Merged into")).toBeVisible();
  await expect(card.getByRole("heading", { name: /Possible duplicates/ })).toHaveCount(0);
  await expect(page.getByText("Showing 1 of 1 contacts.")).toBeVisible();

  await card.getByRole("button", { name: "Undo" }).click();
  await expect(card.getByRole("heading", { name: "Possible duplicates (1)" })).toBeVisible();
  await expect(page.getByText("Showing 2 of 2 contacts.")).toBeVisible();

  await card.getByRole("button", { name: "Not the same" }).click();
  await expect(page.getByText("are not the same")).toBeVisible();
  await expect(card).toHaveCount(0); // remembered: never suggested again

  await page.reload();
  await expect(page.getByLabel("Possible duplicates")).toHaveCount(0);
});
