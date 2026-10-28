import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";
import { RELAY_URL, WEB_URL } from "./env.mjs";

/**
 * Self-employment (MTD Income Tax) through a pretend relay: Playwright answers the relay's /itsa endpoints with
 * HMRC's documented shapes (Business Details 2.0, Obligations 3.0, Self-Employment Business 5.0, Individual
 * Calculations 8.0; see services/hmrc-relay/tests/fixtures/itsa), so no OAuth or HMRC call happens. The figures and
 * receipts are the test-mode runtime's own.
 */
const NINO = "TC663795B";
const BIZ = "XAIS12345678910";
const CALC = "f2fb30e5-4ab6-4a29-b3c1-c7264259ff1c";
const envelope = (hmrc: unknown) => ({
  hmrc, sent_headers: { "gov-client-connection-method": "WEB_APP_VIA_SERVER" }, fraud_headers_missing: [],
  correlation_id: "corr-e2e", receipt_id: null, receipt_timestamp: null,
});

test("off by default; on in Settings it adds Self-employment to the menu", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/settings");
  // Signed in, the main navigation is the menu bar: Self-employment is in its Tax group (lib/nav.ts).
  const nav = page.getByRole("navigation", { name: "Main" });
  const tax = nav.getByRole("button", { name: "Tax" });
  await tax.click();
  await expect(nav.getByRole("link", { name: "VAT returns" })).toBeVisible();
  await expect(nav.getByRole("link", { name: /^Self-employment/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await settingsTab(page, "Business");
  const toggle = page.getByRole("switch", { name: "I am self-employed" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await tax.click();
  await nav.getByRole("link", { name: /^Self-employment/ }).click();
  await expect(page).toHaveURL(/\/self-employment$/);
  await expect(page.getByRole("heading", { name: "Self-employment (MTD Income Tax)" })).toBeVisible();
});

test("accounting basis: cash by default, traditional kept in the books, and a cash-basis profit and loss", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/settings");
  await settingsTab(page, "Business");
  await expect(page.getByRole("radiogroup", { name: "Accounting basis" })).toHaveCount(0); // only for the self-employed
  await page.getByRole("switch", { name: "I am self-employed" }).click();
  const basis = page.getByRole("radiogroup", { name: "Accounting basis" });
  await expect(basis.getByRole("radio", { name: /Cash basis \(default\)/ })).toHaveAttribute("aria-checked", "true");
  await basis.getByRole("radio", { name: /Traditional \(accruals\)/ }).click();
  await expect(page.getByText("Saved. Your self-employment figures now use this basis.")).toBeVisible();

  await page.reload(); // kept in the books, not in this browser
  await settingsTab(page, "Business");
  await expect(
    page.getByRole("radiogroup", { name: "Accounting basis" }).getByRole("radio", { name: /Traditional \(accruals\)/ }),
  ).toHaveAttribute("aria-checked", "true");

  await page.goto("/reports");
  const plBasis = page.getByRole("radiogroup", { name: "Profit and loss basis" });
  await expect(plBasis.getByRole("radio", { name: "As approved" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("heading", { name: /^Profit and loss · / })).toBeVisible();
  await plBasis.getByRole("radio", { name: "Cash basis" }).click();
  await expect(page.getByRole("heading", { name: /^Profit and loss \(cash basis\) · / })).toBeVisible();
  await expect(page.getByText(/^Cash basis: income counts when the customer's money is received/)).toBeVisible();
});

test("connects, lists obligations, shows the figures, submits with confirmation and shows HMRC's calculation", async ({ page }) => {
  test.setTimeout(60_000); // HMRC asks for 5 s between triggering and reading a calculation
  const calls: string[] = [];
  const sent: Record<string, unknown> = {};
  await page.route(`${RELAY_URL}/**`, async (route) => {
    const url = new URL(route.request().url());
    calls.push(url.pathname);
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, json: body, headers: { "Access-Control-Allow-Origin": "*" } });
    const body = route.request().postDataJSON() as Record<string, unknown> | null;
    if (url.pathname === "/hmrc/authorize") {
      sent.scope = url.searchParams.get("scope");
      sent.redirect = url.searchParams.get("redirect_to");
      // a query, so the browser loads the page again, as it does coming back from HMRC
      return json({ url: `${WEB_URL}/self-employment?from=hmrc#code=e2e-code&state=e2e-state`, state: "e2e-state" });
    }
    if (url.pathname === "/hmrc/exchange") return json({ access_token: "hmrc-itsa", refresh_token: "r", expires_in: 14400 });
    if (route.request().headers()["x-hmrc-access-token"] !== "hmrc-itsa") return json({ detail: "wrong token" }, 401);
    if (url.pathname === `/itsa/${NINO}/businesses`)
      return json(envelope({ listOfBusinesses: [
        { typeOfBusiness: "self-employment", businessId: BIZ, tradingType: "Plastering", tradingName: "Sam Builds" },
        { typeOfBusiness: "uk-property", businessId: "XPIS12345678903" },
      ] }));
    if (url.pathname === `/itsa/${NINO}/obligations`) {
      sent.obligations = body;
      return json(envelope({ obligations: [{ typeOfBusiness: "self-employment", businessId: BIZ, obligationDetails: [
        { periodStartDate: "2026-04-06", periodEndDate: "2026-07-05", dueDate: "2026-08-07", receivedDate: "2026-08-01", status: "fulfilled" },
        { periodStartDate: "2026-04-06", periodEndDate: "2026-10-05", dueDate: "2026-11-07", status: "open" },
        { periodStartDate: "2026-04-06", periodEndDate: "2027-01-05", dueDate: "2027-02-07", status: "open" },
      ] }] }));
    }
    if (url.pathname === `/itsa/${NINO}/self-employment/${BIZ}/cumulative/2026-27`) {
      sent.cumulative = body;
      return json(envelope(null)); // HMRC: 204 No Content
    }
    if (url.pathname === `/itsa/${NINO}/calculations/2026-27/trigger`) return json(envelope({ calculationId: CALC }), 202);
    if (url.pathname === `/itsa/${NINO}/calculations/2026-27/${CALC}/view`)
      return json(envelope({
        metadata: { calculationId: CALC, taxYear: "2026-27", calculationType: "in-year" },
        calculation: { taxCalculation: {
          incomeTax: { totalIncomeReceivedFromAllSources: 12500, totalAllowancesAndDeductions: 12500, totalTaxableIncome: 0, incomeTaxCharged: 0 },
          nics: { class4Nics: { totalAmount: 321.4 }, totalNic: 321.4 },
          totalIncomeTaxAndNicsDue: 321.4,
        } },
      }));
    return route.fulfill({ status: 404, json: { detail: "not stubbed" }, headers: { "Access-Control-Allow-Origin": "*" } });
  });

  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/self-employment");
  const hmrcCard = page.getByRole("region", { name: "HMRC: Making Tax Digital for Income Tax" });
  await expect(hmrcCard).toContainText("Sandbox · test data only");
  await hmrcCard.getByRole("button", { name: "Connect to HMRC for Income Tax (sandbox)" }).click();
  await expect(hmrcCard.getByRole("button", { name: "Disconnect" })).toBeVisible();
  expect(sent.scope).toBe("read:self-assessment write:self-assessment");
  expect(sent.redirect).toBe(`${WEB_URL}/self-employment`);
  expect(page.url()).toBe(`${WEB_URL}/self-employment?from=hmrc`); // the code was taken out of the address bar

  await hmrcCard.getByLabel("National Insurance number").fill("tc 66 37 95 b");
  await hmrcCard.getByRole("button", { name: "Show my businesses" }).click();
  await expect(hmrcCard.getByText(`Sam Builds · Plastering · ${BIZ}`)).toBeVisible();
  await expect(hmrcCard.getByText("XPIS12345678903")).toHaveCount(0); // property businesses are not this page's
  const obligations = hmrcCard.getByRole("table", { name: "Quarterly obligations" });
  await expect(obligations.getByRole("radio", { name: "Choose the update to 5 Oct 2026" })).toBeChecked(); // first open one
  expect(sent.obligations).toMatchObject({ from: "2026-04-06", to: "2027-04-05", business_id: BIZ, method: "WEB_APP_VIA_SERVER" });

  const figures = page.getByRole("region", { name: /Your figures, 6 Apr 2026 to 5 Oct 2026/ });
  await expect(figures.getByRole("table", { name: "Self-employment figures" })).toContainText("Turnover: takings, fees, sales");
  await expect(figures.getByLabel("Accounting basis")).toHaveText("Cash basis"); // HMRC's default for sole traders
  await expect(figures).toContainText("Cash basis: income counts when the customer's money is received");
  const submit = figures.getByRole("button", { name: "Submit update to HMRC" });
  await expect(submit).toBeDisabled(); // nothing goes until the user confirms
  await figures.getByRole("checkbox", { name: /I have checked these figures/ }).check();
  await submit.click();
  const receipt = figures.getByRole("status", { name: "Update receipt" });
  await expect(receipt).toContainText("HMRC accepted the update.");
  await expect(receipt).toContainText("corr-e2e");
  await expect(receipt).toContainText("_System/itsa/2026-27/");
  const cumulative = sent.cumulative as { confirmed: boolean; summary: { periodDates: unknown; periodIncome: object; periodExpenses: object } };
  expect(cumulative.confirmed).toBe(true);
  expect(cumulative.summary.periodDates).toEqual({ periodStartDate: "2026-04-06", periodEndDate: "2026-10-05" });
  expect(Object.keys(cumulative.summary.periodIncome).sort()).toEqual(["other", "turnover"]);
  expect(Object.keys(cumulative.summary.periodExpenses)).toHaveLength(15); // zeros included, as HMRC asks

  const download = page.waitForEvent("download");
  await receipt.getByRole("button", { name: "PDF" }).click();
  expect((await download).suggestedFilename()).toBe("quarterly-update-2026-27-to-2026-10-05.pdf");

  const calc = page.getByRole("region", { name: "HMRC's tax calculation" });
  await calc.getByRole("button", { name: "Ask HMRC for a calculation" }).click();
  const table = calc.getByRole("table", { name: "HMRC calculation: HMRC's calculation" });
  await expect(table).toContainText("Total Income Tax and NIC due", { timeout: 15_000 });
  await expect(table).toContainText("£321.40");
  await expect(calc).toContainText("These are HMRC's figures, as HMRC returned them.");
  await expect(page.getByRole("region", { name: "Saved for 2026-27" })).toContainText("HMRC calculation");
  expect(calls.filter((c) => c.startsWith("/itsa/"))).toEqual([
    `/itsa/${NINO}/businesses`,
    `/itsa/${NINO}/obligations`,
    `/itsa/${NINO}/self-employment/${BIZ}/cumulative/2026-27`,
    `/itsa/${NINO}/calculations/2026-27/trigger`,
    `/itsa/${NINO}/calculations/2026-27/${CALC}/view`,
  ]);
});
