import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("a product fills a quote line; send behind the tick, accept, convert to an invoice draft with the same total", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/sales/items");
  await expect(page.getByRole("heading", { name: "No products or services yet" })).toBeVisible();
  await page.getByRole("button", { name: "New item" }).first().click();
  const item = page.getByRole("dialog", { name: "New product or service" });
  await item.getByLabel("Code").fill("LAB-1");
  await item.getByLabel("Name", { exact: true }).fill("Labour");
  await item.getByLabel("Unit", { exact: true }).fill("hours");
  await item.getByLabel("Sale price (£, ex VAT)").fill("45.00");
  await item.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "LAB-1 · Labour" })).toContainText("Sell £45.00");

  await page.goto("/sales/quotes");
  await expect(page.getByRole("heading", { name: "No quotes yet" })).toBeVisible();
  await page.getByRole("button", { name: "New quote" }).click();
  const form = page.getByRole("dialog", { name: "New quote" });
  await form.getByLabel("Name", { exact: true }).fill("Harbour Cafe Ltd");
  await form.getByLabel("Email (the quote is sent here)").fill("accounts@harbourcafe.example");
  await form.getByLabel("Product or service (optional)").selectOption("LAB-1");
  await expect(form.getByLabel("Description")).toHaveValue("Labour");
  await expect(form.getByLabel("Unit price (£, ex VAT)")).toHaveValue("45.00");
  await form.getByLabel("Qty").fill("6");
  await expect(form.getByText("Total£324.00")).toBeVisible(); // 6 x £45.00 + 20% VAT
  await form.getByRole("button", { name: "Save draft" }).click();

  const row = page.getByRole("listitem").filter({ hasText: "QU-0001 · Harbour Cafe Ltd" });
  await expect(row).toContainText("£324.00");
  await row.getByRole("button", { name: "Preview and send" }).click();
  const dialog = page.getByRole("dialog", { name: "Preview and send QU-0001" });
  const send = dialog.getByRole("button", { name: "Send via Outlook" });
  await expect(send).toBeDisabled(); // nothing goes out until the user ticks the confirmation
  expect(await runtime.sent()).toEqual([]);
  await dialog.getByRole("checkbox", { name: /I have checked this quote/ }).check();
  await send.click();
  await expect(row).toContainText("Sent");
  const [mail] = await runtime.sent();
  expect(mail.to).toBe("accounts@harbourcafe.example");
  expect(mail.attachments).toEqual(["QU-0001.pdf"]);

  await row.getByRole("button", { name: "Accepted" }).click();
  await expect(row).toContainText("Accepted");
  await row.getByRole("button", { name: "Convert to invoice" }).click();
  await expect(page.getByRole("status").filter({ hasText: "INV-0001 is a draft invoice" })).toBeVisible();

  await page.goto("/invoices");
  const inv = page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" });
  await expect(inv).toContainText("£324.00");
  await expect(inv).toContainText("Draft");
});

test("a purchase order is approved, sent, and converted to a bill that waits in Review", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/purchases/orders");
  await page.getByRole("button", { name: "New purchase order" }).first().click();
  const form = page.getByRole("dialog", { name: "New purchase order" });
  await form.getByLabel("Name", { exact: true }).fill("Travis Perkins Ltd");
  await form.getByLabel("Email (the order is sent here)").fill("orders@tp.example");
  // A £431.52 bill needs the supplier's VAT number to reclaim its VAT (a full VAT invoice over £250); without one it
  // would wait as "needs a look" (VAT_NUMBER_REQUIRED, tested in test_purchase_orders.py).
  await form.getByLabel("Their VAT number (optional)").fill("GB232555112");
  await form.getByLabel("Description").fill("Plasterboard 12.5mm");
  await form.getByLabel("Qty").fill("40");
  await form.getByLabel("Unit price (£, ex VAT)").fill("8.99");
  await expect(form.getByText("Total£431.52")).toBeVisible(); // £359.60 + £71.92 VAT
  await form.getByRole("button", { name: "Save draft" }).click();

  const row = page.getByRole("listitem").filter({ hasText: "PO-0001 · Travis Perkins Ltd" });
  await expect(row).toContainText("£431.52");
  await row.getByRole("button", { name: "Approve" }).click();
  await row.getByRole("button", { name: "Preview and send" }).click();
  const dialog = page.getByRole("dialog", { name: "Preview and send PO-0001" });
  const send = dialog.getByRole("button", { name: "Send via Outlook" });
  await expect(send).toBeDisabled();
  await dialog.getByRole("checkbox", { name: /I have checked this order/ }).check();
  await send.click();
  await expect(row).toContainText("Sent");
  expect((await runtime.sent())[0].attachments).toEqual(["PO-0001.pdf"]);

  await row.getByRole("button", { name: "Convert to bill" }).click();
  await expect(page.getByRole("status").filter({ hasText: "waiting in Review" })).toBeVisible();
  await expect(row).toContainText("Billed");
  const proposals = await runtime.api<{ extracted: { supplier_name: string; gross_total: number }; status: string }[]>("GET", "/books/proposals");
  expect(proposals.map((p) => [p.extracted.supplier_name, p.extracted.gross_total, p.status])).toEqual([["Travis Perkins Ltd", 431.52, "proposed"]]);

  await page.goto("/purchases");
  await expect(page.getByText("Bills and receipts in Review")).toBeVisible();
  await expect(page.getByRole("link", { name: /Bills and receipts in Review/ })).toContainText("£431.52");
});

test("a repeating monthly invoice makes its drafts when the page opens and shows the next run date", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/sales/repeating");
  await expect(page.getByRole("heading", { name: "Nothing repeats yet" })).toBeVisible();
  await page.getByRole("button", { name: "New repeating item" }).first().click();
  const form = page.getByRole("dialog", { name: "New repeating invoice or bill" });
  await form.getByLabel("Name", { exact: true }).fill("Harbour Cafe Ltd");
  await form.getByLabel("First date").fill("2026-09-15");
  await expect(form.getByText(/Next dates: 15 Sept 2026, 15 Oct 2026/)).toBeVisible();
  await form.getByLabel("Description").fill("Monthly retainer");
  await form.getByLabel("Unit price (£, ex VAT)").fill("100.00");
  await expect(form.getByText(/standing approval/)).toHaveCount(0); // unticked: drafts only
  await form.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("Made from your repeating schedules just now:")).toBeVisible();
  const row = page.getByRole("listitem").filter({ hasText: "Harbour Cafe Ltd · invoice" });
  await expect(row).toContainText("next run 15 Nov 2026");
  await expect(row).toContainText("makes drafts");

  await page.goto("/invoices");
  await expect(page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" })).toContainText("£120.00");
  await expect(page.getByRole("listitem").filter({ hasText: "INV-0002 · Harbour Cafe Ltd" })).toContainText("Draft");
});

test("the Sales overview adds up what is owed and overdue, and a statement is emailed behind the tick", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  const inv = await runtime.api<{ number: string }>("POST", "/invoices", {
    customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
    issue_date: "2026-09-01",
    due_date: "2026-10-01",
    lines: [{ description: "Kitchen first fix", quantity: "6", unit_price_pence: 4500, vat_code: "S" }],
  });
  await runtime.api("POST", `/invoices/${inv.number}/send`, { confirm: true, to: "accounts@harbourcafe.example", subject: "s", body: "b" });
  const before = (await runtime.sent()).length;

  await page.goto("/sales");
  await expect(page.getByRole("link", { name: /^Awaiting payment/ })).toContainText("£324.00");
  await expect(page.getByRole("link", { name: /^Overdue/ })).toContainText("£324.00");
  await expect(page.getByRole("region", { name: "Biggest amounts to chase" })).toContainText("26 days late");
  await expect(page.getByRole("region", { name: "Who owes you, by how late" })).toContainText("1 to 30 days late£324.00");

  await page.getByLabel("Customer", { exact: true }).selectOption({ label: "Harbour Cafe Ltd" });
  await page.getByRole("button", { name: "Open statement" }).click();
  const st = page.getByRole("dialog", { name: "Statement for Harbour Cafe Ltd" });
  await expect(st).toContainText("closing balance £324.00");
  await st.getByRole("button", { name: "Preview PDF and email" }).click();
  const send = page.getByRole("button", { name: "Send via Outlook" });
  await expect(send).toBeDisabled();
  expect((await runtime.sent()).length).toBe(before);
  await page.getByRole("checkbox", { name: /I have checked this statement/ }).check();
  await send.click();
  await expect(page.getByRole("status").filter({ hasText: "Statement sent to Harbour Cafe Ltd" })).toBeVisible();
  const mails = await runtime.sent();
  expect(mails).toHaveLength(before + 1);
  expect(mails[before].attachments).toEqual(["Statement 2026-10-27.pdf"]);
});
