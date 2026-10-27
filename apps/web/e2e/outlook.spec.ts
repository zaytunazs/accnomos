import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("Outlook intake: turn on and preview (dry run) copies nothing", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/settings");
  const intake = page.getByRole("region", { name: "Outlook intake" });
  const toggle = intake.getByRole("switch", { name: "Outlook intake" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(intake).toContainText("Outlook intake is on.");

  await intake.getByRole("button", { name: "Preview what would be imported" }).click();
  const result = intake.getByRole("status");
  // The seeded mailbox: three gold receipts by email and a newsletter whose only attachment is an invite.
  await expect(result).toContainText("3 files would be imported");
  await expect(result).toContainText("4 emails with attachments in the last 14 days");
  await expect(result.getByRole("listitem")).toHaveCount(3);
  await expect(result).toContainText("novexofficesupplies.example_receipt-001.png");
  expect((await runtime.files()).filter((f) => f.startsWith("00 Inbox/"))).toEqual([]);
});
