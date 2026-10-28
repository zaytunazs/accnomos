import { createBooksFolder, expect, signIn, test } from "./fixtures";
import type { Page } from "@playwright/test";

/**
 * Online payments in test mode: the runtime's Stripe and PayPal are the fakes in services/runtime/app/online_fakes.py
 * (their consent screens agree at once; every page stays on 127.0.0.1). Nothing reaches Stripe or PayPal.
 */

async function connect(page: Page, provider: "Stripe" | "PayPal") {
  await page.goto("/settings#settings-payments");
  const card = page.getByRole("region", { name: "Online payments" });
  await card.getByRole("button", { name: `Connect ${provider} (test mode)` }).click();
  // runtime start -> fake consent -> runtime callback -> /settings#pay=… -> connect with this tab's secret
  await expect(page.getByRole("status")).toContainText(`${provider} connected.`);
  await expect(page).not.toHaveURL(/code=|merchant_id=/); // the fragment is cleared at once
  return card;
}

test("Settings: connect Stripe and PayPal in test mode, set a PayPal.me name, disconnect", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  const card = await connect(page, "Stripe");
  await expect(card).toContainText(/Connected: acct_test/);
  await expect(card.getByText("Test mode").first()).toBeVisible();

  await connect(page, "PayPal");
  await expect(card).toContainText("Connected: FAKEMERCHANT1");

  await card.getByLabel("PayPal.me name").fill("SamBuilds");
  await card.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toContainText("PayPal.me name saved.");

  const stored = (await runtime.files()).filter((f) => f.endsWith("providers.json"));
  expect(stored).toEqual(["_System/Payments/providers.json"]);

  await card.getByRole("button", { name: "Disconnect" }).first().click();
  await card.getByRole("button", { name: "Yes, disconnect Stripe" }).click();
  await expect(card.getByRole("button", { name: "Connect Stripe (test mode)" })).toBeVisible();
});

test("Invoice: add a Stripe payment link, the customer pays, approve it with the fee", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await connect(page, "Stripe");

  // £372.00 (6 h × £45 + 4 × £10, 20% VAT), sent through the API (invoices.spec covers writing and sending)
  await runtime.api("POST", "/invoices", {
    customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
    lines: [
      { description: "Kitchen first fix", quantity: "6", unit: "hours", unit_price_pence: 4500, vat_code: "S" },
      { description: "Fixings", quantity: "4", unit: "boxes", unit_price_pence: 1000, vat_code: "S" },
    ],
  });
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true });

  await page.goto("/invoices");
  const row = page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" });
  await row.getByRole("button", { name: "Add payment link" }).click();
  const dialog = page.getByRole("dialog", { name: "Payment link for INV-0001" });
  await expect(dialog).toContainText("£372.00");
  const stripe = dialog.getByRole("radio", { name: /Stripe/ });
  await expect(stripe).toBeChecked({ timeout: 30_000 }); // the only connected account is picked for you
  await dialog.getByRole("button", { name: "Make payment link" }).click();
  const url = await dialog.getByRole("textbox", { name: "Payment link" }).inputValue();
  expect(url).toMatch(/\/__test\/stripe\/pay\/plink_/);
  await expect(dialog.getByRole("button", { name: "Copy payment link for INV-0001" })).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();

  const line = row.getByRole("group", { name: "Payment link for INV-0001" });
  await expect(line).toContainText("Pay online · Stripe · £372.00");
  await expect(line.getByText("Test mode")).toBeVisible();

  // The customer pays on the (fake) Stripe page
  const pay = await page.request.post(url);
  expect(pay.ok()).toBeTruthy();

  // Opening Invoices again finds it; nothing is in the books until approved
  await page.goto("/invoices");
  const paid = page.getByRole("region", { name: "Paid online" });
  await expect(paid).toContainText("INV-0001 · Harbour Cafe Ltd · £372.00 via Stripe");
  await expect(paid).toContainText("Fee £5.78 · you receive £366.22");
  await expect(paid).toContainText("7900 Bank charges (VAT E)");
  expect(await runtime.api<unknown[]>("GET", "/payments")).toEqual([]);
  await paid.getByRole("button", { name: "Approve £372.00 on INV-0001" }).click();
  await expect(page.getByRole("status")).toContainText("£372.00 from Stripe recorded on INV-0001.");
  await expect(paid).toBeHidden();
  await expect(page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" })).toContainText("Paid");
  const payments = await runtime.api<{ amount_pence: number; reference: string }[]>("GET", "/payments");
  expect(payments.map((p) => p.amount_pence)).toEqual([37200]);
});
