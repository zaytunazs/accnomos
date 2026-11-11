import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Power grid add-on (Settings › Business › Power grid), against the test-mode runtime: PayPal is the fake in
 * services/runtime/app/online_fakes.py and the AI is the stub (app/testmode.py grid_filter_reply).
 */

const SHOTS = process.env.E2E_GRID_SHOTS; // a folder: also save screenshots there

test("off by default; on, PayPal opens in the review grid and Approve selected posts only the ticked rows", async ({ page, runtime }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await signIn(page);
  await createBooksFolder(page);

  // Connect PayPal (fake), then sync with the add-on off: the usual card list.
  await page.goto("/settings#settings-payments");
  const payments = page.getByRole("region", { name: "Online payments" });
  await payments.getByRole("button", { name: "Connect PayPal (test mode)" }).click();
  await expect(page.getByRole("status")).toContainText("PayPal connected.");

  await page.goto("/invoices");
  const panel = page.getByRole("region", { name: "PayPal" });
  await panel.getByRole("button", { name: "Sync PayPal" }).click();
  await expect(panel.getByRole("list", { name: "PayPal transactions waiting for approval" })).toBeVisible();
  await expect(page.getByTestId("paypal-grid")).toHaveCount(0);

  // Switch it on in Settings › Business.
  await page.goto("/settings#settings-power-grid");
  await page.getByLabel("Use the power grid").check();
  if (SHOTS) await page.locator("#settings-power-grid").screenshot({ path: `${SHOTS}/power-grid-setting.png` });

  await page.goto("/invoices");
  const grid = page.getByTestId("paypal-grid");
  await expect(grid.locator(".ag-row").first()).toBeVisible();
  await expect(grid.getByText(/Total of \d+ shown \(GBP\)/)).toBeVisible();
  await expect(panel.getByRole("list", { name: "PayPal transactions waiting for approval" })).toHaveCount(0);

  const approve = grid.getByRole("button", { name: /Approve selected/ });
  await expect(approve).toBeDisabled();
  const boxes = grid.getByRole("checkbox", { name: /toggle row selection/ });
  await expect(grid.getByRole("checkbox", { name: /Row Selection is disabled/ }).first()).toBeVisible(); // not waiting
  const selectable = await boxes.count();
  expect(selectable).toBeGreaterThan(0);
  await boxes.first().check();
  await expect(approve).toHaveText("Approve selected (1)");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/paypal-review-grid.png`, fullPage: false });

  page.once("dialog", (d) => void d.accept());
  await approve.click();
  await expect(grid.getByRole("status")).toContainText("1 of 1 approved");
  // Only the ticked row was posted: the runtime has exactly one approved, the rest still waiting.
  const view = await runtime.api<{ items: { status: string }[] }>("GET", "/payments/paypal/sync");
  expect(view.items.filter((i) => i.status === "approved")).toHaveLength(1);
  expect(view.items.filter((i) => i.status === "proposed")).toHaveLength(selectable - 1);

  // Quick filter narrows the rows (and the totals follow).
  await grid.getByLabel("Search the PayPal grid").fill("zzzz-no-such-row");
  await expect(grid.getByText("Total of 0 shown (GBP)")).toBeVisible();
});

test("ledger explorer: plain words become a checked filter", async ({ page, runtime }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await runtime.reset("purchases"); // Jun–Oct 2026 purchases in the ledger
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/reports/ledger-grid");
  await expect(page.getByText("The ledger explorer is part of the Power grid add-on.")).toBeVisible();

  await page.evaluate(() => window.localStorage.setItem("accnomos.powergrid.show", "1"));
  await page.goto("/reports/ledger-grid");
  const grid = page.getByTestId("ledger-grid");
  await expect(grid.getByText(/Total of \d+ lines shown/)).toBeVisible();
  const before = Number((await grid.getByText(/Total of \d+ lines shown/).innerText()).match(/\d+/)?.[0]);
  expect(before).toBeGreaterThan(0);
  await page.getByLabel("Describe the lines you want to see").fill("Lines over £5 in October");
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Lines matching your words.");
  // The stub's filter reached the grid: amount and date are filtered, and fewer lines are shown.
  await expect(page.locator(".ag-header-cell-filtered")).toHaveCount(2);
  await expect(grid.getByText(/Total of \d+ lines shown/)).not.toHaveText(`Total of ${before} lines shown`);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/ledger-explorer.png`, fullPage: false });
});
