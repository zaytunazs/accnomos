import { createBooksFolder, expect, signIn, test } from "./fixtures";

// Load sample books (services/runtime/app/sample_books.py) on the test runtime's fake OneDrive: the whole
// tools/seed_demo.py plan, written in the background as of the pinned day (27 Oct 2026).

test("Load sample books: an empty folder fills with the Bramblewood books, labelled SAMPLE", async ({ page }) => {
  test.slow(); // the full seed, ~60 steps, on the fakes
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/");
  const card = page.getByRole("region", { name: "Try it with sample books" });
  await expect(card).toContainText(
    "Loads six months of a fictional joinery business (labelled SAMPLE) into your Accnomos folder. You can delete it any time by deleting the folder in OneDrive.",
  );
  await card.getByRole("button", { name: "Load sample books" }).focus();
  await page.keyboard.press("Enter");

  const progress = page.getByRole("progressbar", { name: "Loading sample books" });
  await expect(progress).toBeVisible();
  await expect(progress).toHaveAttribute("aria-valuetext", /^\d+ of \d+ steps done/);
  await expect(page.getByRole("heading", { name: "Loading sample books…" })).toBeFocused();

  // Done: Home reloads with the books in it and says they are a sample.
  const banner = page.getByRole("region", { name: "Sample books" });
  await expect(banner).toContainText("SAMPLE — FICTIONAL COMPANY", { timeout: 60_000 });
  await expect(banner).toContainText("sample books for Bramblewood Joinery Ltd");
  const tile = (label: string) => page.getByRole("group", { name: label });
  await expect(tile("Owed to you")).toContainText("£17,950"); // tools/seed_demo.md: £17,949.78 over 6 documents
  await expect(page.getByRole("button", { name: "Load sample books" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Recent activity" })).not.toContainText("Nothing yet");

  // Never offered again once the folder has data, on Connect's last step either.
  await page.goto("/connect/ready");
  await expect(page.getByRole("region", { name: "Sample books" })).toContainText("Sample books are loaded");
  await expect(page.getByRole("button", { name: "Load sample books" })).toHaveCount(0);
});

test("Load sample books is not offered for a folder that already has books", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();

  await page.goto("/");
  await expect(page.getByRole("group", { name: "Owed by you" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Load sample books" })).toHaveCount(0);
  await page.goto("/connect/ready");
  await expect(page.getByRole("heading", { name: "You're connected" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Load sample books" })).toHaveCount(0);
});

test("Connect's last step offers sample books for an empty folder", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/connect/ready");
  await expect(page.getByRole("region", { name: "Try it with sample books" }).getByRole("button", { name: "Load sample books" })).toBeVisible();
});
