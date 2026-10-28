import { expect, test, USER } from "./fixtures";

test("connect: sign in, create the books folder, test the AI", async ({ page, runtime }) => {
  await page.goto("/connect");
  await page.getByRole("button", { name: "Sign in with Microsoft" }).click();

  await expect(page.getByText("Signed in as")).toBeVisible();
  await expect(page.getByText(USER, { exact: true })).toBeVisible();
  await expect(page.getByText("Personal account · folder will be OneDrive › Apps › Accnomos")).toBeVisible();

  await page.getByRole("button", { name: "Create my Accnomos folder" }).click();
  await expect(page.getByText("Your folder is ready.")).toBeVisible();
  expect(await runtime.files()).toContain("README.txt");

  await page.goto("/connect/ai");
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByRole("status")).toContainText("Connected · accnomos-test-stub");
});
