import AxeBuilder from "@axe-core/playwright";
import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";
import { RELAY_URL, WEB_URL } from "./env.mjs";

// SAMPLE — FICTIONAL PROPERTIES: a flat let alone and a house owned with a spouse (stated 60/40, no Form 17).

test("landlord mode: two properties, joint shares, rent and costs, the year and the update file", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/property");
  await expect(page.getByText("Landlord mode is off.")).toBeVisible();
  // Signed in, the main navigation is the menu bar; Property is in Tax (lib/nav.ts) while landlord mode is on.
  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("button", { name: "Tax" }).click();
  await expect(nav.getByRole("link", { name: /Property/ })).toHaveCount(0);
  await nav.getByRole("button", { name: "Tax" }).click();

  await page.goto("/settings");
  const panel = await settingsTab(page, "Business");
  await panel.getByRole("checkbox", { name: "I let property (landlord mode)" }).check();
  await nav.getByRole("button", { name: "Tax" }).click();
  await expect(nav.getByRole("link", { name: /Property/ })).toBeVisible();
  await nav.getByRole("button", { name: "Tax" }).click();
  await expect.poll(async () => (await runtime.api<{ landlord_mode: boolean }>("GET", "/property/settings")).landlord_mode).toBe(true);

  await page.goto("/property");
  const list = page.getByRole("region", { name: "Your properties" });
  await expect(list).toContainText("No properties yet");
  await list.getByLabel("Name", { exact: true }).fill("Flat 2, Mill Court");
  await list.getByLabel("Postcode").fill("ls6 2ab");
  await list.getByRole("checkbox", { name: "Furnished" }).check();
  await list.getByRole("button", { name: "Add property" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Added Flat 2, Mill Court" })).toBeVisible();
  await expect(list).toContainText("LS6 2AB");

  await list.getByText("Add a property").click();
  await list.getByLabel("Name", { exact: true }).fill("14 Oak Road");
  await list.getByRole("combobox", { name: "Who owns it" }).selectOption({ label: "Me and my spouse or civil partner" });
  await list.getByLabel("Other owner's name").fill("Sam");
  await list.getByLabel("Your share (%)").fill("60");
  await list.getByRole("button", { name: "Add property" }).click();
  await expect(list).toContainText("You 60%, Sam 40% (spouses: taxed 50:50 without a Form 17)");

  const record = page.getByRole("region", { name: "Record rent or a cost" });
  async function add(prop: string, what: string, amount: string, date: string, description: string) {
    await record.getByRole("combobox", { name: "Property", exact: true }).selectOption({ label: prop });
    await record.getByRole("combobox", { name: "What it is" }).selectOption({ label: what });
    await record.getByLabel("Amount (£)").fill(amount);
    await record.getByLabel("Date").fill(date);
    await record.getByLabel("Description").fill(description);
    if (what.startsWith("Replacing")) await record.getByRole("checkbox", { name: /replaces an item/ }).check();
    await record.getByRole("button", { name: "Record" }).click();
    await expect(page.getByRole("status").filter({ hasText: `Recorded £${Number(amount).toFixed(2)}` })).toBeVisible();
  }
  await add("Flat 2, Mill Court", "Rents received", "850", "2026-05-01", "May rent");
  await add("Flat 2, Mill Court", "Property repairs and maintenance", "120", "2026-05-20", "Boiler service");
  await add("14 Oak Road", "Rents received", "1200", "2026-06-01", "June rent");
  await add("14 Oak Road", "Mortgage interest and loan costs on residential lets (a tax credit, not an expense)", "400", "2026-06-15", "Mortgage interest");
  await add("14 Oak Road", "Replacing furniture, appliances or kitchenware (like for like)", "300", "2026-07-10", "New fridge for the old one");

  const year = page.getByRole("region", { name: /^Your share for 2026 to 2027/ });
  // Flat £850 + half of Oak Road's £1,200 = £1,450; expenses £120; fridge half £150; profit £1,180.
  await expect(year).toContainText("£1450.00");
  await expect(year).toContainText("£1180.00");
  await expect(year.getByRole("row", { name: /14 Oak Road/ })).toContainText("50%");
  await expect(year).toContainText("£40.00"); // 20% of half of £400 interest
  await expect(year).toContainText("Form 17");

  const entries = page.getByRole("region", { name: "Entries this tax year" });
  await expect(entries.getByRole("listitem")).toHaveCount(5);

  // The quarterly update: the latest quarter that has ended (today 27 Oct 2026: to 5 Oct), SA105 boxes, the file.
  const mtd = page.getByRole("region", { name: "Quarterly update to HMRC" });
  await expect(mtd.getByRole("combobox", { name: "Quarter ending" })).toHaveValue("2026-10-05");
  await expect(mtd).toContainText("Box 20: Total rents and other income from property");
  await expect(mtd).toContainText("Box 44: Residential property finance costs");
  await mtd.getByText("What would be sent").click();
  await expect(mtd.locator("pre")).toContainText('"periodAmount": 1450');
  await expect(mtd.locator("pre")).toContainText('"residentialFinancialCost": 200');
  await mtd.getByRole("button", { name: "Save file ready to submit" }).click();
  await expect(mtd.getByRole("status")).toContainText("07 Reports");
  expect((await runtime.files()).some((f) => f.includes("07 Reports/2026-10-27-uk-property-2026-27-to-2026-10-05"))).toBeTruthy();

  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);
});

test("UK property update through a stubbed relay: connect, find the business, confirm and send (sandbox)", async ({ page, runtime }) => {
  const calls: { path: string; body: unknown }[] = [];
  await page.route(`${RELAY_URL}/**`, async (route) => {
    const url = new URL(route.request().url());
    const req = route.request();
    calls.push({ path: url.pathname, body: req.postData() ? JSON.parse(req.postData()!) : null });
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { "Access-Control-Allow-Origin": "*" } });
    const envelope = (hmrc: unknown) => ({ hmrc, sent_headers: {}, fraud_headers_missing: [], correlation_id: "corr-e2e", receipt_id: null, receipt_timestamp: null });
    if (url.pathname === "/hmrc/authorize") {
      expect(url.searchParams.get("scope")).toBe("read:self-assessment write:self-assessment");
      return json({ url: `${WEB_URL}/property?from=hmrc#code=e2e-code&state=e2e-state`, state: "e2e-state" }); // a new page load, as after the relay
    }
    if (url.pathname === "/hmrc/exchange") return json({ access_token: "hmrc-itsa", refresh_token: "r", expires_in: 14400 });
    if (url.pathname === "/itsa/TC663795B/property/businesses")
      return json(envelope({ listOfBusinesses: [{ typeOfBusiness: "self-employment", businessId: "XAIS00000000001" }, { typeOfBusiness: "uk-property", businessId: "XPIS12345678901" }] }));
    if (url.pathname === "/itsa/TC663795B/property/XPIS12345678901/cumulative/2026-27") return json(envelope(null));
    return json({ detail: "not stubbed" }, 404);
  });

  await signIn(page);
  await createBooksFolder(page);
  await runtime.api("PUT", "/property/settings", { landlord_mode: true });
  const flat = await runtime.api<{ id: string }>("POST", "/property/properties", { name: "Flat 2, Mill Court" });
  await runtime.api("POST", "/property/entries", { property_id: flat.id, date: "2026-05-01", category: "rents", amount_pence: 85000, description: "May rent" });

  await page.addInitScript(() => window.localStorage.setItem("accnomos.landlord.show", "1")); // this device's menu flag
  await page.goto("/property");
  const mtd = page.getByRole("region", { name: "Quarterly update to HMRC" });
  await mtd.getByRole("button", { name: "Connect to HMRC (sandbox)" }).click();
  await expect(mtd.getByRole("button", { name: "Disconnect" })).toBeVisible();
  expect(page.url()).toBe(`${WEB_URL}/property?from=hmrc`); // the code was taken out of the address bar

  await mtd.getByLabel("National Insurance number").fill("tc 66 37 95 b");
  await mtd.getByRole("button", { name: "Find my property business" }).click();
  await expect(mtd.getByLabel("HMRC business ID")).toHaveValue("XPIS12345678901");
  const send = mtd.getByRole("button", { name: "Send update (sandbox)" });
  await expect(send).toBeDisabled();
  await mtd.getByRole("checkbox", { name: /checked these figures/ }).check();
  await send.click();
  await expect(mtd.getByRole("status")).toContainText("Sent to HMRC's sandbox (reference corr-e2e)");
  await expect(mtd.getByRole("list", { name: "Updates sent" })).toContainText("HMRC answered 204");

  const sent = calls.find((c) => c.path.endsWith("/cumulative/2026-27"))!.body as { summary: Record<string, unknown>; confirmed: boolean };
  expect(sent.confirmed).toBe(true);
  expect(sent.summary).toEqual({ fromDate: "2026-04-06", toDate: "2026-10-05", ukProperty: { income: { periodAmount: 850 } } });
  const saved = await runtime.api<{ matched_books: boolean; business_id: string }[]>("GET", "/property/submissions?tax_year=2026-27");
  expect(saved[0]).toMatchObject({ matched_books: true, business_id: "XPIS12345678901" });
  expect((await runtime.api<{ business_id: string }>("GET", "/property/settings")).business_id).toBe("XPIS12345678901");
});
