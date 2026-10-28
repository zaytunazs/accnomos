import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";

/**
 * Accountant collaboration against the test-mode runtime (services/runtime/app/testmode.py): sharing is a fake
 * world with Graph's permission shapes. In the `accountant` seed the signed-in user is the accountant of two
 * clients (Harbour Joinery Ltd: view and edit; Patel Lettings: view only, one query waiting on the client).
 */

test.describe("as the client", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
  });

  test("invite an accountant, see them listed, take access away", async ({ page }) => {
    await page.goto("/settings#settings-accountant");
    const panel = await settingsTab(page, "Your accountant");
    const form = panel.getByRole("form", { name: "Invite your accountant" });
    await form.getByLabel("Their email (Microsoft account)").fill("ana@firm.example");
    await form.getByLabel("Name (optional)").fill("Ana Okafor");
    await form.getByRole("radio", { name: "View only (and leave queries)" }).check();
    await form.getByRole("button", { name: "Invite" }).click();
    await expect(panel.getByRole("status").first()).toContainText("Invited ana@firm.example");
    const people = panel.getByRole("list", { name: "People with access" });
    await expect(people).toContainText("Ana Okafor (ana@firm.example) · View only");
    await expect(panel.getByText("Client code for your accountant's portal: t-drive:t-root")).toBeVisible();

    await people.getByRole("button", { name: "Remove access" }).click();
    await expect(panel.getByRole("status").first()).toContainText("ana@firm.example no longer has access");
    await expect(panel.getByRole("list", { name: "People with access" })).toHaveCount(0);
  });

  test("opting in to Accnomos accountants needs the consent box, and can be stopped", async ({ page }) => {
    await page.goto("/settings#settings-accountant");
    const panel = await settingsTab(page, "Your accountant");
    const team = panel.getByRole("region", { name: "Reviews by Accnomos accountants" });
    const terms = team.getByRole("list", { name: "What opting in means" });
    await expect(terms).toContainText("reviews@accnomos.example");
    await expect(terms).toContainText("They can see everything in it");
    await expect(terms).toContainText("Stop reviews");
    const optIn = team.getByRole("button", { name: "Opt in to reviews" });
    await expect(optIn).toBeDisabled();
    await team.getByRole("checkbox", { name: /I have read this and agree/ }).check();
    await optIn.click();
    await expect(team.getByText(/On since .* shared with reviews@accnomos.example/)).toBeVisible();
    await team.getByRole("button", { name: "Stop reviews" }).click();
    await expect(team.getByRole("button", { name: "Opt in to reviews" })).toBeVisible();
  });
});

test.describe("as the accountant", () => {
  test.beforeEach(async ({ page, runtime }) => {
    await runtime.reset("accountant");
    await signIn(page);
    await createBooksFolder(page);
  });

  test("the portal lists shared books with their deadlines, Review counts and queries", async ({ page }) => {
    await page.goto("/accountant");
    const clients = page.getByRole("list", { name: "Your clients" });
    const hj = clients.getByRole("article", { name: "Harbour Joinery Ltd" });
    const pl = clients.getByRole("article", { name: "Patel Lettings" });
    await expect(hj).toContainText("Business · View and edit");
    await expect(hj).toContainText("Jul–Sep 2026 due 7 Nov 2026 (11 days)");
    await expect(hj).toContainText("Waiting in Review1");
    await expect(pl).toContainText("Landlord · View only");
    await expect(pl).toContainText("Not VAT-registered");
    await expect(pl).toContainText("1 (0 for you, 1 for them)");
    await expect(clients.getByRole("article")).toHaveCount(2); // the shared Photos folder is not books
    await expect(pl.getByRole("button", { name: "Open Patel Lettings to edit" })).toHaveCount(0);
  });

  test("open a client view-only: the usual pages show their books; writes are refused; a query is sent", async ({ page }) => {
    await page.goto("/accountant");
    await page.getByRole("button", { name: "Open Patel Lettings (view only)" }).click();
    const banner = page.getByRole("region", { name: "Client books" });
    await expect(banner).toContainText("Patel Lettings's books");
    await expect(banner).toContainText("View only");

    await page.goto("/review");
    await expect(banner).toBeVisible(); // the tab remembers the client
    await page.getByRole("button", { name: /^Reject / }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Reject" }).click();
    await expect(page.getByText(/read-only/).first()).toBeVisible();

    await page.getByRole("link", { name: "Send a query about this" }).first().click();
    const form = page.getByRole("form", { name: "New query" });
    await expect(form.getByLabel("About")).toHaveValue("proposal");
    await form.getByLabel("Your question").fill("Which property is this for?");
    await form.getByRole("button", { name: "Send query" }).click();
    const threads = page.getByRole("list", { name: "Queries" });
    await expect(threads).toContainText("Which property is this for?");
    await expect(threads).toContainText("Is this rent for Flat 2?"); // the seeded one

    await banner.getByRole("button", { name: "Back to your clients" }).click();
    await expect(page.getByRole("region", { name: "Client books" })).toHaveCount(0);
    await expect(page.getByRole("list", { name: "Your clients" }).getByRole("article", { name: "Patel Lettings" })).toContainText(
      "2 (0 for you, 2 for them)",
    );
  });

  test("add a client by code when Microsoft's shared-with-me list is empty", async ({ page }) => {
    await page.goto("/accountant?client=c2-drive:c2-root");
    const form = page.getByRole("form", { name: "Add a client by code" });
    await expect(form.getByLabel("Client code or link")).toHaveValue("c2-drive:c2-root");
    await form.getByRole("button", { name: "Add client" }).click();
    await expect(form.getByRole("status")).toContainText("Added Accnomos");
    await form.getByLabel("Client code or link").fill("nonsense");
    await form.getByRole("button", { name: "Add client" }).click();
    await expect(form.getByRole("status")).toContainText("not a client code");
  });
});
