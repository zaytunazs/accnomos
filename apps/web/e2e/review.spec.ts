import type { Page } from "@playwright/test";
import { createBooksFolder, expect, GOLD, signIn, test } from "./fixtures";

/** The Review page: keyboard flow, image viewer, edit validation and rule approvals. */

const card = (page: Page, name: string | RegExp) => page.getByRole("region", { name });
const focusedCard = (page: Page) => page.locator("section[aria-labelledby]:focus").getByRole("heading", { level: 2 });

test.describe("signed out: the sample queue", () => {
  test("label, keyboard approve and undo, confirmed reject", async ({ page }) => {
    await page.goto("/review");
    await expect(page.getByText("SAMPLE — FICTIONAL COMPANY · Bramblewood Joinery Ltd.")).toBeVisible();
    await expect(page.getByText("4 waiting for you")).toBeVisible();

    await page.keyboard.press("j");
    await expect(focusedCard(page)).toHaveText("Screwfix · £38.47");
    await page.keyboard.press("j");
    await expect(focusedCard(page)).toHaveText("Screwfix · £21.60");
    await page.keyboard.press("k");
    await expect(focusedCard(page)).toHaveText("Screwfix · £38.47");

    await page.keyboard.press("a");
    await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("Approved · posted to your books · U to undo");
    await expect(card(page, "Screwfix · £38.47")).toHaveCount(0);
    await expect(focusedCard(page)).toHaveText("Screwfix · £21.60"); // focus moved on, not lost

    await page.keyboard.press("u");
    await expect(card(page, "Screwfix · £38.47")).toBeVisible();
    await expect(focusedCard(page)).toHaveText("Screwfix · £38.47");

    await page.keyboard.press("r");
    const confirm = page.getByRole("dialog", { name: "Reject Screwfix · £38.47?" });
    await expect(confirm).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(confirm).toHaveCount(0);
    await expect(card(page, "Screwfix · £38.47")).toBeVisible();
    await page.keyboard.press("r");
    await confirm.getByRole("button", { name: "Reject" }).click();
    await expect(card(page, "Screwfix · £38.47")).toHaveCount(0);
    await expect(focusedCard(page)).toHaveText("Screwfix · £21.60");
  });

  test("failed checks are plain English; never a raw code", async ({ page }) => {
    await page.goto("/review");
    const travis = card(page, "Travis Perkins · £212.40");
    await expect(travis.getByRole("list", { name: "Checks that need you" })).toContainText("Looks like a duplicate of a receipt you approved on 14 Oct");
    await expect(page.locator("main")).not.toContainText(/DUPLICATE|VERIFIER_AGREES|ARITH_TOTALS/);
  });

  test("Approve all N rule matches: one confirm, undo brings them back", async ({ page }) => {
    await page.goto("/review");
    await expect(card(page, "Screwfix · £38.47")).toContainText("Matches your Autopilot rule for Screwfix");
    await expect(card(page, "Novex Office Supplies Ltd · £51.90")).not.toContainText("Matches your Autopilot rule");
    await page.getByRole("button", { name: "Approve all 2 rule matches" }).first().click();
    const confirm = page.getByRole("dialog", { name: "Approve all 2 rule matches?" });
    await confirm.getByRole("button", { name: "Approve 2" }).click();
    await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("Approved 2 of 2 rule matches · posted to your books · U to undo");
    await expect(card(page, /^Screwfix/)).toHaveCount(0);
    await page.keyboard.press("u");
    await expect(card(page, /^Screwfix/)).toHaveCount(2);
  });

  test("rule matches are not offered at L0", async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem("accnomos.autopilot", "L0"));
    await page.goto("/review");
    await expect(page.getByText("4 waiting for you")).toBeVisible();
    await expect(page.getByRole("button", { name: /rule matches/ })).toHaveCount(0);
  });

  test("image: original beside the crop, zoom, Esc closes", async ({ page }) => {
    await page.goto("/review");
    await page.getByRole("button", { name: /Open the document for Novex Office Supplies Ltd · £51.90 \(original and crop/ }).click();
    const viewer = page.getByRole("dialog", { name: "Document: Novex Office Supplies Ltd · £51.90" });
    await expect(viewer.getByRole("img", { name: /^Original document/ })).toBeVisible();
    await expect(viewer.getByRole("img", { name: /^Cropped document/ })).toBeVisible();
    await expect(viewer).toContainText("Cropped by code");
    await viewer.getByRole("button", { name: "What was read: zoom in" }).click();
    await expect(viewer.getByRole("button", { name: "What was read: zoom out" })).toHaveAttribute("aria-pressed", "true");
    await expect(viewer.getByRole("img", { name: /^Original document/ })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(viewer).toHaveCount(0);
  });

  test("edit sheet: highlights the verifier's field, blocks invalid totals, sends only changes", async ({ page }) => {
    await page.goto("/review");
    await card(page, "Novex Office Supplies Ltd · £51.90").getByRole("button", { name: /^Edit/ }).click();
    let sheet = page.getByRole("dialog", { name: "Edit Novex Office Supplies Ltd" });
    await expect(sheet).toContainText("Second reading disagrees: 2026-10-02");
    await page.keyboard.press("Escape"); // focus returns to Novex's Edit button, so Novex is the current card

    await page.keyboard.press("k");
    await page.keyboard.press("k");
    await expect(focusedCard(page)).toHaveText("Screwfix · £38.47");
    await page.keyboard.press("e");
    sheet = page.getByRole("dialog", { name: "Edit Screwfix" });
    const save = sheet.getByRole("button", { name: "Save & approve" });
    await expect(sheet).toContainText("No changes: this approves it as read.");
    await expect(save).toBeEnabled();

    await sheet.getByLabel("Total (£)").fill("38.48");
    await expect(save).toBeDisabled();
    await expect(sheet).toContainText("Can't save yet: Net + VAT is £38.47 but the total is £38.48 (£0.01 short).");
    await sheet.getByLabel("Total (£)").fill("38.47");

    await sheet.getByLabel("VAT (£)").fill("1.00");
    await expect(save).toBeDisabled();
    await expect(sheet).toContainText("VAT code S (standard 20%) expects about £6.41 VAT on £32.06");
    await sheet.getByLabel("VAT (£)").fill("6.41");

    await sheet.getByLabel("Date").fill("2099-01-01");
    await expect(sheet).toContainText("The date is in the future.");
    await sheet.getByLabel("Date").fill("2026-10-20");

    await sheet.getByLabel("VAT number").fill("GB12");
    await expect(sheet).toContainText("That is not a UK VAT number");
    await sheet.getByLabel("VAT number").fill("GB232555112");

    await sheet.getByLabel("Category").selectOption("Materials");
    await expect(sheet).toContainText("2 changes will be sent with the approval.");
    await save.click();
    await expect(sheet).toHaveCount(0);
    await expect(card(page, "Screwfix · £38.47")).toHaveCount(0);
  });
});

test("signed in: edit sends only changed fields, U undoes through the runtime, preview reads OneDrive", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/review");
  await page.locator('input[type="file"]').first().setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
  await expect(page.getByText("1 file added to 00 Inbox")).toBeVisible();
  await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("1 new proposal");
  const novex = card(page, "Novex Office Supplies Ltd · £51.90");
  await expect(novex).toBeVisible();
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY")).toHaveCount(0);

  await novex.getByRole("button", { name: /^Open the document for Novex/ }).click();
  const viewer = page.getByRole("dialog", { name: /^Document: Novex/ });
  await expect(viewer.getByRole("img", { name: /^Original document/ })).toBeVisible();
  await viewer.getByRole("button", { name: "Close the document" }).click();

  const bodies: unknown[] = [];
  page.on("request", (r) => r.url().includes("/approve") && r.method() === "POST" && bodies.push(r.postDataJSON()));
  await novex.getByRole("button", { name: /^Edit/ }).click();
  const sheet = page.getByRole("dialog", { name: /^Edit Novex/ });
  await sheet.getByLabel("Category").selectOption("Materials");
  await sheet.getByRole("button", { name: "Save & approve" }).click();
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("Approved · posted to your books · U to undo");
  expect(bodies).toEqual([{ remember: false, edits: { category: "Materials" } }]);
  await expect(novex).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Nothing waiting/ })).toBeFocused();

  await page.keyboard.press("u");
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toContainText("a reversing entry was added; it is back in Review");
  await expect(novex).toBeVisible();
  expect((await runtime.files()).filter((f) => f.startsWith("_System/Ledger/events/"))).toHaveLength(2); // posting + reversal
});
