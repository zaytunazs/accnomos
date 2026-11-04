import AxeBuilder from "@axe-core/playwright";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// Calendar (components/calendar, /calendar routes). The test runtime's today is Tue 27 Oct 2026 and its fake
// calendar holds one event: "Site meeting, Harbour Lane kitchen", Thu 29 Oct 09:00–10:00.

test("list, add with a clash warning, add anyway, remove", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/calendar");
  await expect(page.getByRole("heading", { name: "Calendar", level: 1 })).toBeVisible();
  const days = page.getByRole("list", { name: "Events by day" });
  await expect(days).toContainText("Site meeting, Harbour Lane kitchen");
  await expect(days).toContainText("12 Harbour Lane");

  // a clash is said before anything is written; Cancel writes nothing
  await page.getByRole("button", { name: "+ Add an event" }).click();
  const form = page.getByRole("form", { name: "Add an event" });
  await form.getByLabel("Title").fill("Call with the accountant");
  await form.getByLabel("Date").fill("2026-10-29");
  await form.getByLabel("Time (leave empty for all day)").fill("09:30");
  await form.getByRole("button", { name: "Add to calendar" }).click();
  const clash = form.locator("[data-clash]");
  await expect(clash).toContainText("Clashes with ‘Site meeting, Harbour Lane kitchen’ 09:00–10:00");
  await clash.getByRole("button", { name: "Cancel" }).click();
  await expect(clash).toHaveCount(0);
  await expect(days).not.toContainText("Call with the accountant");

  await form.getByRole("button", { name: "Add to calendar" }).click();
  await form.locator("[data-clash]").getByRole("button", { name: "Add anyway" }).click();
  await expect(page.getByText("Added “Call with the accountant”.")).toBeVisible();
  await expect(days).toContainText("Call with the accountant");

  // no clash: added straight away, all day
  await page.getByRole("button", { name: "+ Add an event" }).click();
  await form.getByLabel("Title").fill("Pick up van");
  await form.getByLabel("Date").fill("2026-10-30");
  await form.getByRole("button", { name: "Add to calendar" }).click();
  await expect(page.getByText("Added “Pick up van”.")).toBeVisible();
  await expect(days).toContainText("Pick up van");

  // remove asks first
  await page.getByRole("button", { name: "Remove Pick up van" }).click();
  await page.getByRole("button", { name: "Keep" }).click();
  await expect(days).toContainText("Pick up van");
  await page.getByRole("button", { name: "Remove Pick up van" }).click();
  await page.getByRole("button", { name: "Yes, remove" }).click();
  await expect(page.getByText("Removed “Pick up van”.")).toBeVisible();
  await expect(days).not.toContainText("Pick up van");

  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(axe.violations).toEqual([]);
});

test("deadlines sync twice without duplicates, and the switch is saved", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/calendar");
  const panel = page.locator("[data-calendar-sync]");
  await expect(panel).toContainText("Uses your Microsoft 365 / Outlook calendar");
  await panel.getByRole("button", { name: "Add to calendar" }).click();
  await expect(panel).toContainText(/Done: \d+ added/);
  const days = page.getByRole("list", { name: "Events by day" });
  await expect(days).toContainText("Added by Accnomos");
  const first = await days.getByText("Added by Accnomos").count();
  expect(first).toBeGreaterThan(0);

  await panel.getByRole("button", { name: "Add to calendar" }).click();
  await expect(panel).toContainText("Your calendar already has every deadline.");
  await page.reload();
  await expect(days).toContainText("Added by Accnomos");
  expect(await days.getByText("Added by Accnomos").count()).toBe(first);
  // "updated HH:MM" on the day; the browser's clock is pinned to the test day, the server stamps real time
  await expect(panel).toContainText(/deadlines? in your calendar · updated (\d\d:\d\d|\d{1,2} [A-Z][a-z]{2})/);

  const toggle = panel.getByRole("switch", { name: "Add all deadlines to my calendar automatically" });
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  await expect(toggle).toBeChecked();
  await page.reload();
  await expect(panel.getByRole("switch", { name: "Add all deadlines to my calendar automatically" })).toBeChecked();
});

test("the menu's Your plan section links to Calendar", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  // wide screens: Your plan is its own section of the sidebar (under More on the bar and in the drawer)
  await nav.getByRole("link", { name: "Calendar", exact: true }).click();
  await expect(page).toHaveURL(/\/calendar$/);
  await expect(page.getByRole("heading", { name: "Calendar", level: 1 })).toBeVisible();
});

test("Home › Deadlines: one deadline goes into the calendar and then says so", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();

  await page.goto("/");
  const deadlines = page.getByRole("region", { name: "Deadlines" });
  await expect(deadlines).toContainText("VAT period"); // loaded
  await deadlines.getByRole("button", { name: /^Add to calendar: VAT return/ }).click();
  await expect(deadlines.getByText("In your calendar ✓").first()).toBeVisible();
  await expect(deadlines.getByRole("button", { name: /^Add to calendar: VAT/ })).toHaveCount(0);
  await expect(deadlines.locator("[data-calendar-sync]")).toContainText("Added to your calendar: VAT return");
  await page.reload();
  await expect(deadlines.getByText("In your calendar ✓").first()).toBeVisible();
  await expect(deadlines.locator("[data-calendar-sync]")).toContainText("1 deadline in your calendar");

  // only that one: the other deadlines are still to add from the panel
  await page.goto("/calendar");
  const days = page.getByRole("list", { name: "Events by day" });
  await expect(days).toContainText("Site meeting, Harbour Lane kitchen");
});
