import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";

test("Your data: export saves the zip and names it; leaving says what to delete", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // one posted purchase, so every table has something in it

  await page.goto("/settings");
  const data = await settingsTab(page, "Your data");
  await expect(data.getByRole("heading", { name: "Export your data" })).toBeVisible();
  await expect(data.getByRole("heading", { name: "What is stored where" })).toBeVisible();
  await expect(data.getByRole("heading", { name: "Leave Accnomos" })).toBeVisible();

  await data.getByRole("button", { name: "Export your data" }).click();
  await expect(data.getByRole("status")).toContainText("accnomos-export-2026-10-27.zip");
  expect(await runtime.files()).toContain("07 Reports/Exports/accnomos-export-2026-10-27.zip");

  await expect(data.getByText("nothing is stored server-side")).toBeVisible();
  await expect(data.getByRole("link", { name: "account.live.com/myapps" })).toHaveAttribute(
    "href",
    "https://account.live.com/myapps",
  );
});
