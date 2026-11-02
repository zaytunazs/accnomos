import type { Page } from "@playwright/test";
import { RUNTIME_URL } from "./env.mjs";
import { expect, test, TODAY } from "./fixtures";

// The personal demo (services/runtime/app/demo_personal.py, POST /demo/session?kind=personal): a fictional household's
// own money, next to the company demo. Its books build in about a second, so no seed wait here.

const bar = (page: Page) => page.getByRole("complementary", { name: "Demo sandbox" });

test("the personal demo opens a household's books from /judges, and its bar offers the company demo", async ({ page }) => {
  test.setTimeout(120_000);
  await page.clock.install({ time: TODAY });
  await page.goto("/judges");
  await page.getByRole("button", { name: "Start the personal demo" }).click();
  await expect(page).toHaveURL(/\/personal$/, { timeout: 60_000 });
  await expect(bar(page)).toContainText("SAMPLE — FICTIONAL HOUSEHOLD");
  await expect(bar(page)).toContainText("Demo sandbox with sample data — changes reset after 2 hours.");
  await expect(bar(page).getByRole("button", { name: "Switch to the company demo" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Budget", level: 1 })).toBeVisible();

  // The runtime holds a household: personal profile, bank lines, and goals with mixed statuses.
  const session = await page.evaluate(() => JSON.parse(window.localStorage.getItem("msal.accnomos-demo.session") ?? "{}"));
  expect(session.kind).toBe("personal");
  expect(session.business).toBe("The Patel household (fictional)");
  const goals = await page.request.get(`${RUNTIME_URL}/books/goals?note_ai=false`, {
    headers: { "X-Demo-Session": session.session, "X-User": "demo@accnomos.example" },
  });
  expect(goals.ok()).toBe(true);
  const view = (await goals.json()) as { household: boolean; goals: { status: string }[] };
  expect(view.household).toBe(true);
  expect(view.goals).toHaveLength(5);
  for (const s of ["on_track", "at_risk", "off_track"]) expect(view.goals.map((g) => g.status)).toContain(s);
});

test("the landing page offers both demos", async ({ page }) => {
  await page.goto("/");
  const main = page.getByRole("main");
  await expect(main.getByRole("link", { name: "Try the demo", exact: true }).first()).toHaveAttribute("href", "/judges");
  await expect(main.getByRole("link", { name: "Try the personal demo" }).first()).toHaveAttribute("href", "/judges"); // the guide explains both when scripts or demos are off
});
