import { createBooksFolder, expect, signIn, test } from "./fixtures";

/** Contacts › Import contacts: Outlook (selected, then all) and the people who email you, each marked when already
 * in the books; a second import adds nothing. */
test("contacts: import selected and all from Outlook, then from people who email you", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/contacts");

  await page.getByRole("button", { name: "Import contacts" }).first().click();
  const panel = page.getByRole("region", { name: "Import contacts" });
  const list = panel.getByRole("list", { name: "Contacts to import" });
  await expect(list.getByRole("listitem").first()).toBeVisible();
  const total = await list.getByRole("listitem").count();
  expect(total).toBeGreaterThan(1);

  // Selected: clear everything, tick one, make it a supplier, import it.
  await panel.getByRole("button", { name: "Clear" }).click();
  await expect(panel.getByRole("button", { name: "Import 0" })).toBeDisabled();
  const first = list.getByRole("listitem").first();
  const name = (await first.locator("span.font-bold").textContent())!.trim();
  await first.getByRole("checkbox").check();
  await first.getByRole("combobox").selectOption("supplier");
  await panel.getByRole("button", { name: "Import 1" }).click();
  await expect(page.getByRole("status")).toContainText("Imported 1.");
  const after: { contacts: { name: string; kind: string }[] } = await runtime.api("GET", "/contacts");
  expect(after.contacts.find((c) => c.name === name)?.kind).toBe("supplier");

  // All: the one just imported is now marked and unticked; Select all + Import imports the rest and skips it.
  await page.getByRole("button", { name: "Import contacts" }).first().click();
  await expect(panel.getByText(/Already in your books/).first()).toBeVisible();
  await panel.getByRole("button", { name: "Select all" }).click();
  await panel.getByRole("button", { name: `Import ${total}` }).click();
  await expect(page.getByRole("status")).toContainText(`Imported ${total - 1}, skipped 1 already in your books.`);

  // People who email you: senders from the inbox, newsletters left out; all already in the books now.
  await page.getByRole("button", { name: "Import contacts" }).first().click();
  await panel.getByRole("tab", { name: "People who email you" }).click();
  await expect(panel.getByText(/emailed you in the last 180 days/)).toBeVisible();
  await expect(list).not.toContainText("Trade Weekly");
  await expect(list.getByRole("listitem").first()).toBeVisible();
  await expect(panel.getByRole("button", { name: "Import 0" })).toBeDisabled(); // every sender is already a contact
  await panel.getByRole("button", { name: "Close" }).click();
  await expect(panel).toHaveCount(0);
});
