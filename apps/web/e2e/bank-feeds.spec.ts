import { join } from "node:path";
import { createBooksFolder, expect, signIn, test } from "./fixtures";
import { RUNTIME_URL } from "./env.mjs";
import type { Page } from "@playwright/test";

/**
 * Bank feeds in test mode: the runtime's TrueLayer is the fake in services/runtime/app/bankfeed_fakes.py (its bank
 * picker agrees at once; every page stays on 127.0.0.1). The mock bank's six transactions (SAMPLE — FICTIONAL
 * COMPANY) include three the gold Barclays CSV also has, worded as a feed words them.
 */
const BARCLAYS = join(__dirname, "../../../evals/gold/bank/barclays.csv");
const BANK = "Mock UK Bank (sandbox)";

async function connect(page: Page) {
  await page.goto("/bank");
  const card = page.getByRole("region", { name: "Bank feed" });
  await expect(card.getByText("Sandbox", { exact: true })).toBeVisible();
  // runtime start -> fake bank picker -> runtime callback -> /bank#feed=… -> connect with this tab's secret -> fetch
  await card.getByRole("button", { name: "Connect a bank (sandbox)" }).click();
  await expect(card.getByRole("status")).toContainText("Fetched from your bank feed:");
  await expect(page).not.toHaveURL(/code=/); // the fragment is cleared at once
  return card;
}

test("connect a bank in the sandbox; the feed leaves out what the statement CSV already had", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");

  const card = await connect(page);
  await expect(card.getByRole("status")).toHaveText(
    "Fetched from your bank feed: 3 new lines (3 lines already in a statement, left out).",
  );
  await expect(card).toContainText(BANK);
  await expect(card).toContainText("Business Current Account ····5678");
  await expect(card).toContainText("Consent runs to 25 Jan 2027."); // 90 days from the pinned 27 Oct 2026

  const files = await runtime.files();
  expect(files).toContain("_System/bankfeeds.json");
  expect(files).toContain("04 Bank statements/2026-10-26_feed.csv");
  const stored = await (await page.request.get(`${RUNTIME_URL}/__test/graph/v1.0/me/drive/special/approot:/_System/bankfeeds.json:/content`)).text();
  expect(stored).not.toMatch(/fake-refresh|fake-access/); // the refresh token is sealed, the access token never kept

  const lines = page.getByRole("region", { name: "Bank lines" });
  await lines.getByRole("tab", { name: /^Unmatched/ }).click();
  await expect(lines.getByText("B&Q WARRINGTON").first()).toBeVisible();
  await expect(lines.getByText("SCREWFIX DIRECT", { exact: true })).toHaveCount(0); // the feed's copy was left out

  await card.getByRole("button", { name: "Fetch now" }).click();
  await expect(card.getByRole("status")).toHaveText("Fetched from your bank feed: 0 new lines.");
});

test("feed first, then the CSV imports only the lines the feed did not have", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  const card = await connect(page);
  await expect(card.getByRole("status")).toHaveText("Fetched from your bank feed: 6 new lines.");

  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText(
    "3 new lines (3 already imported, 3 from your bank feed)",
  );
});

test("the app asks to reconfirm before the consent ends, and reconfirming extends it", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await connect(page);

  // Nine days of consent left: as if it had been given 81 days ago.
  const url = `${RUNTIME_URL}/__test/graph/v1.0/me/drive/special/approot:/_System/bankfeeds.json:/content`;
  const feeds = await (await page.request.get(url)).json();
  feeds.connections[0].consent_expires_at = "2026-11-05T09:00:00Z";
  await runtime.putFile("_System/bankfeeds.json", JSON.stringify(feeds));

  await page.goto("/");
  const strip = page.getByRole("note", { name: "Bank feed" });
  await expect(strip).toContainText(`${BANK}: Your 90-day consent ends in 9 days (5 Nov 2026). Reconfirm to keep it going.`);
  await strip.getByRole("link", { name: "Reconfirm on Bank" }).click();

  const ask = page.getByRole("group", { name: `Reconfirm ${BANK}` });
  await expect(ask).toContainText("Keep sharing");
  await ask.getByRole("button", { name: "Reconfirm for 90 days" }).click();
  const card = page.getByRole("region", { name: "Bank feed" });
  await expect(card.getByRole("status")).toHaveText(`${BANK}: consent reconfirmed. Consent runs to 25 Jan 2027.`);
  await expect(ask).toBeHidden();

  await card.getByRole("button", { name: "Disconnect" }).click();
  await card.getByRole("button", { name: `Yes, disconnect ${BANK}` }).click();
  await expect(card.getByRole("button", { name: "Connect a bank (sandbox)" })).toBeVisible();
});
