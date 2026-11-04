import type { Page } from "@playwright/test";
import { RUNTIME_URL } from "./env.mjs";
import { expect, test, TODAY } from "./fixtures";

// The demo's bank feed (docs/BANK_FEED_SANDBOX_DEMO.md): in a demo session the Bank page connects TrueLayer's sandbox
// test bank, labelled as such, into the demo's own books. TrueLayer here is the runtime's test-mode stand-in
// (services/runtime/app/bankfeed_fakes.py: its bank picker agrees at once and every page stays on 127.0.0.1).
// The personal demo builds in about a second, so no seed wait; the company demo's Bank page is the same component.

const LABEL = "Bank sandbox (TrueLayer test bank) — no real bank data";

async function startDemo(page: Page) {
  await page.clock.install({ time: TODAY });
  await page.goto("/demo");
  await page.getByRole("button", { name: "Start the personal demo" }).click();
  await expect(page).toHaveURL(/:\d+\/$/, { timeout: 60_000 });
}

function demoHeaders(page: Page) {
  return page.evaluate(() => {
    const s = JSON.parse(window.localStorage.getItem("msal.accnomos-demo.session") ?? "{}") as { session: string };
    return { "X-Demo-Session": s.session, "X-User": "demo@accnomos.example" };
  });
}

test("the demo connects TrueLayer's test bank, round trip and all, and fetches its lines into the demo", async ({ page }) => {
  test.setTimeout(120_000);
  await startDemo(page);
  await page.goto("/bank");
  const card = page.getByRole("region", { name: "Bank feed" });
  await expect(card.getByTestId("bank-sandbox-label")).toHaveText(LABEL);
  const login = card.getByRole("group", { name: "TrueLayer test bank login" });
  await expect(login.getByTestId("bank-test-username")).toHaveText("john");
  await expect(login.getByTestId("bank-test-password")).toHaveText("doe");
  await expect(login.getByRole("button", { name: "Copy Password" })).toBeVisible();
  await expect(card).not.toContainText(/OneDrive/);

  const headers = await demoHeaders(page);
  // runtime start -> (stand-in) TrueLayer -> runtime callback -> /bank#feed=… -> connect in this demo -> fetch
  const toTrueLayer = page.waitForRequest((r) => r.url().includes("/__test/truelayer/"));
  await card.getByRole("button", { name: "Connect the test bank" }).click();
  const auth = new URL((await toTrueLayer).url());
  expect(auth.searchParams.get("providers")).toBe("uk-cs-mock"); // the mock bank only
  expect(auth.toString()).not.toContain(headers["X-Demo-Session"]); // the session id never goes to TrueLayer
  await expect(card.getByRole("status")).toContainText("Fetched from your bank feed:");
  await expect(page).not.toHaveURL(/code=/);
  await expect(card).toContainText("Mock UK Bank (sandbox)");
  await expect(card).toContainText("test bank, sample data only");
  await expect(card.getByTestId("bank-sandbox-label")).toHaveText(LABEL);
  await expect(card.getByRole("button", { name: "Fetch now" })).toBeVisible();

  // In the demo's own books, nowhere else.
  const status = await (await page.request.get(`${RUNTIME_URL}/books/bankfeeds`, { headers })).json();
  expect(status.demo).toBe(true);
  expect(status.connections).toHaveLength(1);
  const statements = await (await page.request.get(`${RUNTIME_URL}/books/bank/statements`, { headers })).json();
  expect(statements.map((s: { bank: string }) => s.bank)).toContain("feed");

  await card.getByRole("button", { name: "Fetch now" }).click();
  await expect(card.getByRole("status")).toHaveText("Fetched from your bank feed: 0 new lines.");
});

test("a demo on a server without TrueLayer's sandbox says why, and offers nothing to connect", async ({ page }) => {
  test.setTimeout(120_000);
  await startDemo(page);
  const reason =
    "Bank sandbox is not set up on this server, so the demo cannot connect a test bank. Upload a statement CSV instead: it is matched the same way.";
  await page.route(`${RUNTIME_URL}/books/bankfeeds`, (route) =>
    route.fulfill({
      json: { available: false, reason, provider: "TrueLayer", sandbox: true, reconfirm_days: 14, connections: [], demo: true, label: LABEL, test_login: null },
    }),
  );
  await page.goto("/bank");
  const card = page.getByRole("region", { name: "Bank feed" });
  await expect(card).toContainText(reason);
  await expect(card.getByRole("button", { name: /Connect/ })).toHaveCount(0);
  await expect(card.getByRole("group", { name: "TrueLayer test bank login" })).toHaveCount(0);
});
