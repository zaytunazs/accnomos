import { createBooksFolder, expect, signIn, test } from "./fixtures";

// SAMPLE — FICTIONAL COMPANIES (services/runtime/app/sample_purchases.py, the runtime's `purchases` seed): Jun–Oct 2026
// purchases with line items. Oct 2026: £404.00 before VAT over 5 purchases; Sep 2026: £61.40. The stub AI writes a
// summary from the facts it is sent, and app/ai/spending.py checks every figure in it.

test.beforeEach(async ({ page, runtime }) => {
  await runtime.reset("purchases");
  await signIn(page);
  await createBooksFolder(page);
});

test("Spending: Home card, the checked summary and the breakdown", async ({ page }) => {
  await page.goto("/");
  const tile = page.getByRole("region", { name: "Spending", exact: true });
  await expect(tile).toContainText("£404.00");
  await expect(tile).toContainText("Oct 2026, before VAT · +£342.60 on Sep 2026");
  await tile.getByRole("link", { name: "Open spending" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Spending" })).toBeVisible();
  const summary = page.getByRole("region", { name: "Oct 2026" });
  await expect(summary).toContainText("You spent £404.00 before VAT in Oct 2026 across 5 purchases.");
  await expect(summary).toContainText("Numbers by code · summary by accnomos-test-stub, every figure checked against your books");
  const categories = page.getByRole("table", { name: "By category" });
  await expect(categories.getByRole("row", { name: /Materials/ })).toContainText("£65.00");
  await expect(categories.getByRole("row", { name: /Materials/ })).toContainText("+£53.60 (+470.2%)");
  await expect(page.getByRole("region", { name: "Regular costs" })).toContainText("Cloudnine Software Ltd · subscription");
  await expect(page.getByRole("region", { name: "Unusual one-offs" })).toContainText("Harbour Tools Ltd");
  await expect(page.getByRole("region", { name: "Top items" })).toContainText("Mitre saw 254mm");

  // Last month: Sep 2026 against Aug 2026
  await page.getByRole("radio", { name: "Last month" }).click();
  await expect(page.getByRole("region", { name: "Sep 2026" })).toContainText("£61.40");
});

test("Cheaper options: history only, live search off, a confirmed match shows the cheaper supplier", async ({ page }) => {
  await page.goto("/prices");
  await expect(page.getByRole("note", { name: "Live price search" })).toContainText("Live price search is off");
  await expect(page.getByText(/comes only from receipts and bills already in your books/)).toBeVisible();
  const brown = page.getByRole("article", { name: "Tesa 50mm x 66m Brown Packing Tape" });
  await expect(brown).toContainText("Could save £10.80 a year");
  await expect(brown).toContainText("£0.0288 per metre · Parcelworks Supplies Ltd, 8 Sep 2026");

  // Brown 50 mm and clear 48 mm: the stub AI says "same" and code's size rules agree, so they join (not stored).
  await page.getByRole("button", { name: "Ask your AI which match" }).click();
  await expect(page.getByText(/code kept only those its rules allow/)).toBeVisible();
  const joined = page.getByRole("article", { name: "Packing Tape Clear 48mm x 66m" });
  await expect(joined).toContainText("2 names joined (ai+rules)");
  await expect(joined).toContainText("£0.0250 per metre · Boxmart Ltd");

  // Reload: the AI's view was not kept; the user says yes, and that is.
  await page.reload();
  await page.getByRole("button", { name: "Same product" }).click();
  await expect(page.getByRole("article", { name: "Packing Tape Clear 48mm x 66m" })).toContainText("2 names joined (user)");
  await page.reload();
  await expect(page.getByRole("article", { name: "Packing Tape Clear 48mm x 66m" })).toContainText("2 names joined (user)");
});

test("Shopping list: pick from history, or give the specs; tick off; purchase orders are switched off", async ({ page }) => {
  await page.goto("/shopping");
  await expect(page.getByRole("note", { name: "Live price search" })).toContainText("Live price search is off");
  const add = page.getByRole("form", { name: "Add an item" });
  await add.getByLabel("What do you need?").fill("packing tape");
  await add.getByRole("button", { name: "Look up" }).click();
  await expect(page.getByText("Which one? Last time: Packing Tape Clear 48mm x 66m, £1.65 each from Boxmart Ltd (14 Oct 2026)")).toBeVisible();
  await page.getByRole("radio", { name: /Tesa 50mm x 66m Brown Packing Tape/ }).check();
  await page.getByLabel("Quantity").fill("6");
  await page.getByRole("button", { name: "Add to list" }).click();
  const list = page.getByRole("list", { name: "Shopping list" });
  await expect(list).toContainText("6 × Tesa 50mm x 66m Brown Packing Tape");
  await expect(list).toContainText("Parcelworks Supplies Ltd, £11.40 (the lowest price per metre in your books)");

  await add.getByLabel("What do you need?").fill("masking tape");
  await add.getByRole("button", { name: "Look up" }).click();
  await expect(page.getByText("I can't find “masking tape” in your receipts.")).toBeVisible();
  await page.getByLabel("Width (mm)").fill("25");
  await page.getByLabel("Length (m)").fill("50");
  await page.getByLabel("Quantity").fill("3");
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(list).toContainText("3 × masking tape 25mm x 50m");
  await expect(list).toContainText("No supplier in your books yet");

  await list.getByRole("checkbox", { name: /masking tape/ }).check();
  await expect(page.getByRole("heading", { name: "To buy (1)" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Turn into a purchase order" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Draft email to supplier" })).toBeDisabled();
});

test("Ask: add to the shopping list asks which one, then a card that waits for Approve", async ({ page }) => {
  await page.goto("/ask");
  await page.getByLabel("Ask your books").fill("add 6 packing tape to my shopping list");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByText("Which one? Last time:")).toBeVisible();
  await page.getByRole("button", { name: "Packing Tape Clear 48mm x 66m" }).click();
  const card = page.getByRole("article", { name: "Proposed: Shopping list" });
  await expect(card).toContainText("Packing Tape Clear 48mm x 66m");
  await expect(card).toContainText("Boxmart Ltd · £1.65");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByRole("status")).toContainText("Added 6 × Packing Tape Clear 48mm x 66m to your shopping list.");
  await page.goto("/shopping");
  await expect(page.getByRole("list", { name: "Shopping list" })).toContainText("6 × Packing Tape Clear 48mm x 66m");
});

test("Ask: nothing in the history asks for the specs as fields", async ({ page }) => {
  await page.goto("/ask");
  await page.getByLabel("Ask your books").fill("add 2 masking tape to my shopping list");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const form = page.getByRole("form", { name: "Item details" });
  await expect(form.getByLabel("Quantity")).toHaveValue("2");
  await form.getByLabel("Width (mm)").fill("25");
  await form.getByRole("button", { name: "Continue" }).click();
  const card = page.getByRole("article", { name: "Proposed: Shopping list" });
  await expect(card).toContainText("masking tape 25mm");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByRole("status")).toContainText("Added 2 × masking tape 25mm");
});

test("Ask: summarise my spending answers from the checked summary", async ({ page }) => {
  await page.goto("/ask");
  await page.getByLabel("Ask your books").fill("Summarise my spending");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.getByRole("article").first();
  await expect(answer).toContainText(/Spent before VAT/);
  await expect(answer.getByRole("link", { name: "Open Spending" })).toHaveAttribute("href", "/spending");
});
