import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";

const LINKED = "receipts@sambuilds-mail.example"; // msal-test.ts's default popup account

test("Email intake: add a Microsoft mailbox, check both, set its folder and senders, remove it", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/settings");
  const panel = await settingsTab(page, "Automation");
  const section = panel.getByRole("region", { name: "Email intake" });
  const list = section.getByRole("list", { name: "Mailboxes" });

  // The signed-in mailbox is always there; Gmail and (for a personal account) shared mailboxes are not offered.
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list.getByRole("listitem", { name: "sam@sambuilds.example" })).toContainText("Signed-in account");
  await expect(section.getByRole("button", { name: "Gmail (coming soon)" })).toBeDisabled();
  await expect(section).toContainText("Gmail needs a Google Cloud app");
  await expect(section.getByRole("button", { name: "Add shared mailbox" })).toBeDisabled();
  await expect(section).toContainText("Shared mailboxes need a work or school account");

  // A second Microsoft account through the (fake) popup sign-in.
  await section.getByRole("button", { name: "Add Microsoft mailbox" }).click();
  await expect(section.getByRole("status")).toContainText(`${LINKED} added`);
  const linked = list.getByRole("listitem", { name: LINKED });
  await expect(linked).toContainText("Microsoft account · Not checked yet");
  await expect(linked).not.toContainText("Signed out");

  // Stored in the books without any token.
  expect(await runtime.files()).toContain("_System/mail/mailboxes.json");
  const stored = await runtime.api<{ mailboxes: Record<string, unknown>[] }>("GET", "/mail/mailboxes");
  expect(stored.mailboxes.map((m) => m.address)).toEqual(["sam@sambuilds.example", LINKED]);
  expect(JSON.stringify(stored)).not.toContain("test-token");

  // One check reads both: the linked mailbox's copy of a receipt the signed-in one also got is not copied twice.
  const intake = panel.getByRole("region", { name: "Outlook intake" });
  await intake.getByRole("switch", { name: "Outlook intake" }).click();
  await intake.getByRole("button", { name: "Check my inbox now" }).click();
  const result = intake.getByRole("status").filter({ hasText: "imported" });
  await expect(result).toContainText("4 files imported");
  const byMailbox = intake.getByTestId("intake-by-mailbox");
  await expect(byMailbox).toContainText("sam@sambuilds.example: 3 files");
  await expect(byMailbox).toContainText(`${LINKED}: 1 file, 1 already in your books`);
  expect((await runtime.files()).filter((f) => f.startsWith("00 Inbox/"))).toHaveLength(4);
  await expect(linked).toContainText(/Last checked .+ · 1 file/);

  // Folder and senders for the linked mailbox.
  await linked.getByText("Folder and senders").click();
  await linked.getByLabel("Folder to watch").selectOption("archive");
  await linked.getByLabel("Never from").fill("spam.example, @offers.example");
  await linked.getByRole("button", { name: "Save" }).click();
  await expect(section.getByRole("status")).toContainText(`Saved for ${LINKED}`);
  const saved = await runtime.api<{ mailboxes: { address: string; folder: string; deny_senders: string[] }[] }>(
    "GET",
    "/mail/mailboxes",
  );
  expect(saved.mailboxes[1]).toMatchObject({ folder: "archive", deny_senders: ["spam.example", "offers.example"] });

  // Remove: gone from the list and from this browser's sign-ins; what it copied stays.
  await section.getByRole("button", { name: `Remove ${LINKED}` }).click();
  await expect(section.getByRole("status")).toContainText(`${LINKED} removed`);
  await expect(list.getByRole("listitem")).toHaveCount(1);
  expect(await page.evaluate(() => window.localStorage.getItem("msal.accnomos-test.linked"))).toBe("[]");
  expect((await runtime.files()).filter((f) => f.startsWith("00 Inbox/"))).toHaveLength(4);
});

test("Email intake: a mailbox this browser is not signed in to is listed and reported, not read", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.api("POST", "/mail/mailboxes", { address: "office@elsewhere.example", kind: "microsoft" });

  await page.goto("/settings");
  const panel = await settingsTab(page, "Automation");
  const row = panel
    .getByRole("region", { name: "Email intake" })
    .getByRole("listitem", { name: "office@elsewhere.example" });
  await expect(row).toContainText("Signed out in this browser");
  await expect(row.getByRole("button", { name: "Sign in again" })).toBeVisible();

  const intake = panel.getByRole("region", { name: "Outlook intake" });
  await intake.getByRole("switch", { name: "Outlook intake" }).click();
  await intake.getByRole("button", { name: "Preview what would be imported" }).click();
  await expect(intake.getByRole("status").filter({ hasText: "would be imported" })).toContainText("3 files would be imported");
  await expect(intake.getByTestId("intake-by-mailbox")).toContainText(
    "office@elsewhere.example: not read: sign in to it again under Email intake",
  );
});

test("a linked mailbox's account shares the sign-in cache but is never offered as a profile", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/settings");
  const section = (await settingsTab(page, "Automation")).getByRole("region", { name: "Email intake" });
  await section.getByRole("button", { name: "Add Microsoft mailbox" }).click();
  await expect(section.getByRole("status")).toContainText(`${LINKED} added`);
  await page.goto("/");
  await page.getByRole("button", { name: /^Profile: / }).click();
  const profiles = page.getByRole("menu", { name: "Profiles" }).getByRole("menuitemradio");
  await expect(profiles).toHaveCount(1); // Sam's books only, not the receipts mailbox
  await expect(profiles).not.toContainText(LINKED);
});
