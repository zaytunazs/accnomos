import { createBooksFolder, expect, pickVatPeriod, signIn, test } from "./fixtures";
import { RELAY_URL, WEB_URL } from "./env.mjs";

/**
 * The HMRC card through a pretend relay: Playwright answers the relay's endpoints, so no OAuth or HMRC call
 * happens. Checks the card renders, the PKCE round trip lands back on /vat connected, and obligations list.
 */
test("HMRC card renders, connects through a stubbed relay and lists obligations", async ({ page }) => {
  const calls: string[] = [];
  await page.route(`${RELAY_URL}/**`, async (route) => {
    const url = new URL(route.request().url());
    calls.push(url.pathname);
    const json = (body: unknown) => route.fulfill({ json: body, headers: { "Access-Control-Allow-Origin": "*" } });
    if (url.pathname === "/hmrc/authorize") return json({ url: `${WEB_URL}/vat?from=hmrc#code=e2e-code&state=e2e-state`, state: "e2e-state" });
    if (url.pathname === "/hmrc/exchange") return json({ access_token: "hmrc-test", refresh_token: "r", expires_in: 14400 });
    if (url.pathname === "/vat/123456789/obligations")
      return json({
        hmrc: { obligations: [{ periodKey: "26A3", start: "2026-07-01", end: "2026-09-30", due: "2026-11-07", status: "O" }] },
        sent_headers: {}, fraud_headers_missing: [], correlation_id: null, receipt_id: null, receipt_timestamp: null,
      });
    return route.fulfill({ status: 404, json: { detail: "not stubbed" }, headers: { "Access-Control-Allow-Origin": "*" } });
  });

  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/vat");
  const card = page.getByRole("region", { name: "Connect to HMRC" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Sandbox · test data only");

  await card.getByRole("button", { name: "Connect to HMRC (sandbox)" }).click();
  await expect(card.getByRole("button", { name: "Disconnect" })).toBeVisible();
  expect(page.url()).toBe(`${WEB_URL}/vat?from=hmrc`); // the code was taken out of the address bar

  await card.getByLabel("VAT registration number").fill("123456789");
  await card.getByRole("button", { name: "Show obligations" }).click();
  await expect(card.getByRole("cell", { name: "26A3", exact: true })).toBeVisible();
  await expect(card.getByRole("radio", { name: "Choose period 26A3" })).toBeChecked(); // matches the live return's quarter
  await expect(card.getByRole("list", { name: "Submission steps" })).toBeVisible(); // declaration → submit → receipt
  await expect(card.getByText("No receipts saved yet")).toBeVisible(); // 06 VAT returns/ is empty
  expect(calls).toEqual(["/hmrc/authorize", "/hmrc/exchange", "/vat/123456789/obligations"]);
});

/**
 * A return filed elsewhere (HMRC says fulfilled) shows as submitted with HMRC's date, and an
 * obligation on dates that are not our periods warns in plain English. The card posts HMRC's
 * list to the runtime, so after a reload the picker and the return card know without asking HMRC again.
 */
test("an obligation fulfilled elsewhere shows filed with HMRC's date; foreign dates warn", async ({ page }) => {
  await page.route(`${RELAY_URL}/**`, async (route) => {
    const url = new URL(route.request().url());
    const json = (body: unknown) => route.fulfill({ json: body, headers: { "Access-Control-Allow-Origin": "*" } });
    if (url.pathname === "/hmrc/authorize") return json({ url: `${WEB_URL}/vat?from=hmrc#code=e2e-code&state=e2e-state`, state: "e2e-state" });
    if (url.pathname === "/hmrc/exchange") return json({ access_token: "hmrc-test", refresh_token: "r", expires_in: 14400 });
    if (url.pathname === "/vat/123456789/obligations")
      return json({
        hmrc: {
          obligations: [
            { periodKey: "26A3", start: "2026-07-01", end: "2026-09-30", due: "2026-11-07", status: "F", received: "2026-10-05" },
            { periodKey: "26A4", start: "2026-10-01", end: "2026-12-31", due: "2027-02-07", status: "O" },
            // not one of our quarters: our stagger differs from what HMRC holds
            { periodKey: "26A9", start: "2026-08-01", end: "2026-10-31", due: "2026-12-07", status: "F", received: "2026-11-20" },
          ],
        },
        sent_headers: {}, fraud_headers_missing: [], correlation_id: null, receipt_id: null, receipt_timestamp: null,
      });
    return route.fulfill({ status: 404, json: { detail: "not stubbed" }, headers: { "Access-Control-Allow-Origin": "*" } });
  });

  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/vat");
  const card = page.getByRole("region", { name: "Connect to HMRC" });
  await card.getByRole("button", { name: "Connect to HMRC (sandbox)" }).click();
  await expect(card.getByRole("button", { name: "Disconnect" })).toBeVisible();
  await card.getByLabel("VAT registration number").fill("123456789");
  await card.getByRole("button", { name: "Show obligations" }).click();
  await expect(card.getByRole("cell", { name: "26A3", exact: true })).toBeVisible();

  await page.goto("/vat"); // the picker refetches: HMRC's list is in the runtime now
  await expect(page.getByText("does not match your VAT periods")).toBeVisible();
  await pickVatPeriod(page, "Jul–Sep 2026"); // en dash: the picker's own label (see fixtures.pickVatPeriod)
  await expect(page.getByText("Filed with HMRC on 5 Oct 2026")).toBeVisible();
});
