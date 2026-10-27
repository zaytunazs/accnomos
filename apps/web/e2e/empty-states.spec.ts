import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";
import { RUNTIME_URL } from "./env.mjs";

/**
 * Empty books, signed in: every list says what it is for and what to do
 * first (one sentence plus one action) — never a bare "No data". And when
 * the runtime does not answer, every page offers Try again with the plain
 * sentence, never a status code.
 */

test("empty books: every list names its next step", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/contacts");
  await expect(page.getByRole("heading", { name: "No contacts yet" })).toBeVisible();
  // The toolbar button plus the empty state's own next step.
  await expect(page.getByRole("button", { name: "Import from Outlook" })).toHaveCount(2);

  await page.goto("/invoices");
  await expect(page.getByRole("heading", { name: "No invoices yet" })).toBeVisible();
  await expect(page.getByRole("link", { name: "New invoice" }).first()).toBeVisible();

  await page.goto("/jobs");
  await expect(page.getByRole("heading", { name: "No jobs yet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add your first job" })).toBeVisible();

  await page.goto("/vehicles");
  await expect(page.getByRole("heading", { name: "No vehicles yet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add your first vehicle" })).toBeVisible();

  await page.goto("/bank");
  await expect(page.getByRole("heading", { name: "No statements yet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Upload your first statement" })).toBeVisible();

  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "No receipts waiting" })).toBeVisible();

  await page.goto("/audit");
  await expect(page.getByRole("heading", { name: "Nothing in this range" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Show everything" })).toBeVisible();

  await page.goto("/ask");
  await expect(page.getByRole("heading", { name: "No questions yet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask your first question" })).toBeVisible();

  await page.goto("/settings");
  const panel = await settingsTab(page, "Automation");
  await expect(panel.getByRole("heading", { name: "No rules yet" })).toBeVisible();
  await expect(panel.getByRole("link", { name: "Go to Review" })).toBeVisible();
});

test("runtime down: the error keeps its sentence and offers Try again", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  // Fail every runtime call from here on; the folder already exists.
  let down = true;
  await page.route((url) => down && url.href.startsWith(RUNTIME_URL), (route) => route.abort());

  await page.goto("/contacts");
  const note = page.getByRole("alert").filter({ hasText: /Could not read your contacts/ });
  await expect(note).toBeVisible();
  await expect(note.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/\(status \d{3}\)/);

  // Back up: Try again reloads into the working runtime and the empty state returns.
  down = false;
  await note.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "No contacts yet" })).toBeVisible();
});
