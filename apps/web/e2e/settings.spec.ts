import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
});

test("all five tabs render their sections", async ({ page }) => {
  await page.goto("/settings");
  const expected = {
    Connection: ["Connections", "Audit log", "Disconnect"],
    AI: ["AI", "Second reading (verifier)"],
    Automation: ["Autopilot level", "Outlook intake", "Inbox triage"],
    Business: ["On your invoices", "VAT periods"],
    "Your data": ["Export your data", "What is stored where", "Leave Accnomos"],
  } as const;
  for (const [tab, headings] of Object.entries(expected) as [keyof typeof expected, readonly string[]][]) {
    const panel = await settingsTab(page, tab);
    for (const name of headings) await expect(panel.getByRole("heading", { name, exact: true })).toBeVisible();
    await expect(page.getByRole("tabpanel")).toHaveCount(1); // the others are hidden
  }
  await expect((await settingsTab(page, "Connection")).getByRole("region", { name: "Connections" })).toContainText("Signed in");
});

test("Autopilot L2, monthly VAT and Outlook intake persist across a reload; the tab is remembered", async ({ page }) => {
  await page.goto("/settings");
  const automation = await settingsTab(page, "Automation");
  const autopilot = automation.getByRole("radiogroup", { name: "Autopilot level" });
  await expect(autopilot.getByRole("radio", { name: /L1 Assist/ })).toHaveAttribute("aria-checked", "true");
  await autopilot.getByRole("radio", { name: /L2 Autopilot/ }).click();
  const intake = automation.getByRole("switch", { name: "Outlook intake" });
  await intake.click();
  await expect(intake).toHaveAttribute("aria-checked", "true");

  const business = await settingsTab(page, "Business");
  await business.getByRole("radiogroup", { name: "VAT return period" }).getByRole("radio", { name: "Monthly" }).click();

  await page.reload();
  await expect(page.getByRole("tab", { name: "Business" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("radiogroup", { name: "VAT return period" }).getByRole("radio", { name: "Monthly" })).toHaveAttribute("aria-checked", "true");
  await settingsTab(page, "Automation");
  await expect(autopilot.getByRole("radio", { name: /L2 Autopilot/ })).toHaveAttribute("aria-checked", "true");
  await expect(autopilot.getByRole("radio", { name: /L1 Assist/ })).toHaveAttribute("aria-checked", "false");
  await expect(intake).toHaveAttribute("aria-checked", "true");
});

test("changing the VAT period moves the deadlines on Home", async ({ page }) => {
  const deadlines = page.getByRole("region", { name: "Deadlines" });
  await page.goto("/");
  await expect(deadlines).toContainText("7 NOV: VAT return Jul–Sep 2026 due"); // quarterly, Jan/Apr/Jul/Oct quarters
  await expect(deadlines).toContainText("31 DEC: VAT period Oct–Dec 2026 ends");

  await page.goto("/settings");
  const business = await settingsTab(page, "Business");
  await business.getByRole("radio", { name: "Monthly" }).click();
  await expect(business.getByRole("status")).toHaveText("Saved on this device.");

  await page.goto("/");
  await expect(deadlines).toContainText("7 NOV: VAT return Sep 2026 due");
  await expect(deadlines).toContainText("31 OCT: VAT period Oct 2026 ends");
});

test("deep links open the right tab: #settings-staff, and Home's #automation", async ({ page }) => {
  await page.goto("/settings#settings-staff");
  await expect(page.getByRole("tab", { name: "Business" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#settings-staff")).toBeInViewport();

  await page.goto("/");
  await page.getByRole("link", { name: "Turn on Inbox triage in Settings" }).click();
  await expect(page).toHaveURL(/\/settings#automation$/);
  await expect(page.getByRole("tab", { name: "Automation" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "Inbox triage" })).toBeVisible();
});

test("Business: 'VAT-registered' is saved to the invoice profile; a VAT number always means registered", async ({ page, runtime }) => {
  await page.goto("/settings");
  const business = await settingsTab(page, "Business");
  const profile = business.getByRole("region", { name: "On your invoices" });
  const registered = profile.getByRole("checkbox", { name: /This business is VAT-registered/ });
  await profile.getByLabel("VAT registration number").fill("");
  await expect(registered).toBeChecked(); // the default: receipts need the supplier's VAT number
  await registered.uncheck();
  await profile.getByRole("button", { name: "Save invoice details" }).click();
  await expect(profile.getByRole("status")).toContainText("Saved in your OneDrive");
  expect((await runtime.api<{ vat_registered: boolean }>("GET", "/invoices/profile")).vat_registered).toBe(false);

  await profile.getByLabel("VAT registration number").fill("GB 123 4567 89");
  await expect(registered).toBeChecked();
  await expect(registered).toBeDisabled();
});

test("the account menu names the AI chosen in Settings", async ({ page }) => {
  // Signed in, the menu bar replaces the sidebar; the AI line is in the account menu (src/components/ProfileMenu.tsx).
  const account = page.getByRole("button", { name: /^Account: / });
  const menu = page.getByRole("menu", { name: "Account" });
  await account.click();
  await expect(menu).toContainText("stub answers (test mode)");
  await page.keyboard.press("Escape");

  await page.goto("/settings");
  const ai = await settingsTab(page, "AI");
  await ai.getByRole("button", { name: "My own Meta API key" }).click();
  await ai.getByRole("button", { name: /Save.*Continue/ }).click();
  await account.click();
  await expect(menu).toContainText("Muse Spark key (muse-spark-1.3)");
});
