import { createBooksFolder, expect, signIn, test } from "./fixtures";

/** Files polish: direct files are listed under their folder and previewable; tree keyboard works. */
test("Files lists direct files and previews JSON as text", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();
  await runtime.putFile("01 Receipts/notes.json", '{"hello":"world"}');

  await page.goto("/files");
  const tree = page.getByRole("list").filter({ hasText: "00 Inbox" }).first();
  await expect(tree.getByText("01 Receipts", { exact: true })).toBeVisible();

  // A file directly inside a folder is listed (not only counted) and previews as text with a copy button.
  await expect(tree.getByText("notes.json", { exact: true })).toBeVisible();
  await tree.getByRole("button", { name: "notes.json" }).click();
  const preview = page.getByLabel("Preview: notes.json");
  await expect(preview).toBeVisible();
  await expect(preview.getByText('"hello"')).toBeVisible();
  await expect(preview.getByRole("button", { name: "Copy" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" }).getByText("notes.json")).toBeVisible();
  await preview.getByRole("button", { name: "Close preview" }).click();
  await expect(preview).toHaveCount(0);

  // Arrow keys move between rows.
  await tree.getByRole("button", { name: "00 Inbox" }).focus();
  await page.keyboard.press("ArrowDown");
  await expect(tree.getByRole("button", { name: "01 Receipts" })).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(tree.getByRole("button", { name: "00 Inbox" })).toBeFocused();

  // Books.xlsx card and the upload section are on the page.
  await expect(page.getByRole("heading", { name: "Books.xlsx" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Add files" })).toBeVisible();
});
