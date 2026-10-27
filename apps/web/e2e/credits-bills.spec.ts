import { createBooksFolder, expect, signIn, test, type Runtime } from "./fixtures";

/** Credits on contacts (apply / refund), paying bills from Contacts, payment terms, and one bank movement counted once. */

async function twoInvoices(runtime: Runtime) {
  for (const [qty, desc] of [["6", "Kitchen first fix"], ["1", "Callout"]]) {
    await runtime.api("POST", "/invoices", {
      customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
      lines: [{ description: desc, quantity: qty, unit: "hours", unit_price_pence: 4500, vat_code: "S" }],
    });
  }
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true }); // 6 h × £45 + 20% = £324.00
  await runtime.api("POST", "/invoices/INV-0002/send", { confirm: true }); // £45 + 20% = £54.00
}

test("an overpayment is applied to another invoice and the rest refunded; Remove takes it back", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await twoInvoices(runtime);
  await runtime.api("POST", "/invoices/INV-0001/payments", { amount_pence: 40000, paid_on: "2026-10-27" }); // £76 over

  await page.goto("/invoices");
  const second = page.getByRole("listitem").filter({ hasText: "INV-0002 · Harbour Cafe Ltd" });
  await second.getByRole("button", { name: "Apply credit" }).click();
  const apply = page.getByRole("dialog", { name: "Apply credit for Harbour Cafe Ltd" });
  await expect(apply.getByLabel("Amount (£)")).toHaveValue("54.00"); // as much as both allow
  await expect(apply).toContainText("nothing new is posted");
  await apply.getByRole("button", { name: "Apply credit" }).click();
  await expect(page.getByRole("status")).toContainText("£54.00 of Harbour Cafe Ltd's credit applied to INV-0002.");
  await expect(second.getByRole("button", { name: "Apply credit" })).toHaveCount(0); // reloaded: nothing left to pay
  await expect(second.getByRole("button", { name: "Record payment" })).toHaveCount(0);

  // The £22 left is refunded from INV-0001
  const first = page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" });
  await first.getByRole("button", { name: "Refund" }).click();
  const refund = page.getByRole("dialog", { name: "Refund Harbour Cafe Ltd" });
  await expect(refund.getByLabel("Amount (£)")).toHaveValue("22.00");
  await expect(refund).toContainText("Dr 1100 Debtors / Cr 1200 Bank");
  await refund.getByRole("button", { name: "Record refund" }).click();
  await expect(page.getByRole("status")).toContainText("Refund of £22.00 to Harbour Cafe Ltd recorded.");
  await expect(first.getByRole("button", { name: "Refund" })).toHaveCount(0);
  expect(await runtime.api("GET", "/credits")).toEqual([]);

  // Remove the applied credit on INV-0002: it is owed again
  await second.getByText("Payments and history").click();
  const panel = second.getByRole("region", { name: "Payments on INV-0002" });
  await expect(panel).toContainText("Credit applied (overpaid on INV-0001)");
  await panel.getByRole("button", { name: "Remove payment of £54.00 on INV-0002" }).click();
  await expect(page.getByRole("status")).toContainText("Payment removed from INV-0002.");
  await expect(second.getByRole("button", { name: "Record payment" })).toBeVisible();

  // Contacts shows the refund on the statement and what is left to use
  await page.goto("/contacts");
  await page.getByRole("button", { name: "Refresh from books" }).click();
  await page.getByRole("button", { name: "Harbour Cafe Ltd" }).click();
  const side = page.getByRole("complementary", { name: "Harbour Cafe Ltd: statement" });
  await expect(side.getByRole("table").getByRole("row").filter({ hasText: "Credit refunded" })).toContainText("£22.00");
  const money = side.getByRole("region", { name: "Money with Harbour Cafe Ltd" });
  await expect(money).toContainText("Credit on account");
  await expect(money).toContainText("£54.00");
  await money.getByRole("button", { name: "Apply credit" }).click();
  const again = page.getByRole("dialog", { name: "Apply credit for Harbour Cafe Ltd" });
  await expect(again.getByLabel("Invoice")).toContainText("INV-0002"); // the only one still owed, chosen
  await again.getByRole("button", { name: "Apply credit" }).click();
  await expect(side.getByRole("status")).toContainText("applied to INV-0002");
  await expect(money).toContainText("Credit used");
  await money.getByRole("button", { name: "Remove: Credit applied to INV-0002" }).click();
  await expect(side.getByRole("status")).toContainText("taken back");
});

test("pay a bill from Contacts, overpay it, have the supplier refund the credit; payment terms", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  // A bill on account: the gold Novex receipt (£51.90) approved as not yet paid
  await runtime.dropInInbox();
  const scan = await runtime.api<{ proposals: { id: string }[] }>("POST", "/books/scan");
  await runtime.api("POST", `/books/approve/${scan.proposals[0].id}`, { edits: { payment_method: "unknown" } });

  await page.goto("/contacts");
  await page.getByRole("button", { name: "Refresh from books" }).click();
  await page.getByRole("button", { name: "Novex Office Supplies Ltd" }).click();
  const side = page.getByRole("complementary", { name: "Novex Office Supplies Ltd: statement" });
  const money = side.getByRole("region", { name: "Money with Novex Office Supplies Ltd" });
  await expect(money).toContainText("Bills to pay");
  await expect(money).toContainText("balance £51.90");

  await money.getByRole("button", { name: /^Record payment on/ }).click();
  let pay = page.getByRole("dialog", { name: /^Record payment on/ });
  await expect(pay).toContainText("balance £51.90");
  await pay.getByLabel("Amount (£)").fill("20.00");
  await expect(pay).toContainText("£31.90 stays to pay.");
  await pay.getByRole("button", { name: "Record payment" }).click();
  await expect(side.getByRole("status")).toContainText("£31.90 still to pay.");
  await expect(money).toContainText("paid £20.00");
  await expect(money).toContainText("balance £31.90");

  await money.getByRole("button", { name: /^Record payment on/ }).click();
  pay = page.getByRole("dialog", { name: /^Record payment on/ });
  await pay.getByLabel("Amount (£)").fill("40.00");
  await expect(pay).toContainText("£8.10 more than the balance is kept as a credit Novex Office Supplies Ltd owes you.");
  await pay.getByRole("button", { name: "Record payment" }).click();
  await expect(side.getByRole("status")).toContainText("is paid.");
  await expect(money).toContainText("Credit on account");
  await expect(money).toContainText("Novex Office Supplies Ltd owes you");

  await money.getByRole("button", { name: "Refund" }).click();
  const refund = page.getByRole("dialog", { name: "Refund from Novex Office Supplies Ltd" });
  await expect(refund.getByLabel("Amount (£)")).toHaveValue("8.10");
  await expect(refund).toContainText("Dr 1200 Bank / Cr 2100 Creditors");
  await refund.getByRole("button", { name: "Record refund" }).click();
  await expect(side.getByRole("status")).toContainText("Novex Office Supplies Ltd's refund of £8.10 recorded.");
  await expect(money).not.toContainText("Credit on account");

  // Take the second payment back from the statement: the bill is owed again (the refund must go first)
  const statement = side.getByRole("table");
  await statement.getByRole("button", { name: /^Remove credit refunded to you/ }).click();
  await expect(side.getByRole("status")).toContainText("taken back");
  await statement.getByRole("button", { name: /^Remove payment made of £40.00/ }).click();
  await expect(money).toContainText("balance £31.90");

  // Payment terms per contact, used by ageing
  await side.getByRole("button", { name: "Edit" }).click();
  await side.getByRole("textbox", { name: "Payment terms (days)" }).fill("400");
  await side.getByRole("button", { name: "Save" }).click();
  await expect(side.getByRole("alert")).toContainText("0 to 365");
  await side.getByRole("textbox", { name: "Payment terms (days)" }).fill("14");
  await side.getByRole("button", { name: "Save" }).click();
  await expect(side).toContainText("14 days");
  const contacts = await runtime.api<{ contacts: { name: string; terms_days: number | null }[] }>("GET", "/contacts");
  expect(contacts.contacts.find((c) => c.name === "Novex Office Supplies Ltd")?.terms_days).toBe(14);
});

test("a statement line for a recorded payment links to it, not the invoice again; a Bank-page match posts as a payment", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await twoInvoices(runtime);
  await runtime.api("POST", "/invoices/INV-0001/payments", { paid_on: "2026-10-27" }); // £324.00, no statement yet

  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles({
    name: "oct.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Date,Description,Amount\n27/10/2026,HARBOUR CAFE INV-0001,324.00\n27/10/2026,HARBOUR CAFE INV-0002,54.00\n"),
  });
  await expect(page.getByRole("status").filter({ hasText: "oct.csv" })).toContainText("2 new lines");
  const lines = page.getByRole("region", { name: "Bank lines" });
  const table = lines.getByRole("table");
  await expect(table).toContainText("Recorded payment of £324.00 on 27/10/2026 (Harbour Cafe Ltd)");
  await table.getByRole("button", { name: /^Confirm match: HARBOUR CAFE INV-0001/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Matched" })).toContainText("Matched HARBOUR CAFE INV-0001");

  // Counted once: INV-0001 is paid, not overpaid, and nothing is left on account
  const inv1 = await runtime.api<{ money: { payment_status: string; overpaid_pence: number } }>("GET", "/invoices/INV-0001");
  expect(inv1.money).toMatchObject({ payment_status: "paid", overpaid_pence: 0 });
  expect(await runtime.api("GET", "/credits")).toEqual([]);

  // The reverse: INV-0002's line matched straight on the Bank page posts nothing; Post as payment puts it in the books
  await table.getByRole("button", { name: /^Confirm match: HARBOUR CAFE INV-0002/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Matched" })).toContainText("Matched HARBOUR CAFE INV-0002");
  await page.goto("/invoices");
  const second = page.getByRole("listitem").filter({ hasText: "INV-0002 · Harbour Cafe Ltd" });
  await second.getByText("Payments and history").click();
  await second.getByRole("button", { name: /^Post the bank line of £54.00 as a payment/ }).click();
  await expect(page.getByRole("status")).toContainText("now a recorded payment on INV-0002");
  const pays = await runtime.api<{ source: string; amount_pence: number }[]>("GET", "/payments");
  expect(pays.map((p) => [p.source, p.amount_pence]).sort()).toEqual([["recorded", 32400], ["recorded", 5400]]);
});
