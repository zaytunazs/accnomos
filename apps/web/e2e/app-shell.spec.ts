import { createBooksFolder, expect, settingsTab, signIn, test, USER } from "./fixtures";
import { RUNTIME_URL } from "./env.mjs";

/**
 * The signed-in app shell (src/components/AppShell.tsx, TopBar.tsx, AppFooter.tsx): the menu bar and footer on
 * every page, no accountant link for normal users, the accountant portal's own shell, a silent Microsoft token that
 * times out, earlier files never read, and Back up now. docs/reviews/app-shell/REVIEW.md has the screenshots.
 */

const NAME = "Sam Builder (test)"; // src/lib/msal-test.ts TEST_ACCOUNT
const SHOTS = "../../docs/reviews/app-shell";

test.describe("signed in", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
  });

  test("the top bar: logo, menus with sub-menus, search, Ask, review count, name, email, profile, switcher, sign out", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const bar = page.getByRole("banner").filter({ has: page.getByRole("navigation", { name: "Main" }) });
    await expect(bar.getByRole("link", { name: "Accnomos home" })).toHaveAttribute("href", "/");
    const nav = bar.getByRole("navigation", { name: "Main" });
    await nav.getByRole("button", { name: /^Sales/ }).click();
    await expect(nav.getByRole("link", { name: "Invoices", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(bar.getByRole("button", { name: "Search" })).toBeVisible();
    await expect(bar.getByRole("link", { name: "Ask", exact: true })).toHaveAttribute("href", "/ask");
    await expect(bar.getByRole("link", { name: /^Notifications: / })).toHaveAttribute("href", "/review");

    // The signed-in person's name and Microsoft email, on the bar itself (not only inside the menu).
    const account = bar.getByRole("button", { name: `Account: ${USER} ${NAME}` });
    await expect(account).toContainText(NAME);
    await expect(account).toContainText(USER);

    // The current profile with its kind, and the switcher.
    const profile = bar.getByRole("button", { name: /^Profile: / });
    await expect(profile).toContainText(/Company|Sole trader|Personal|Profile not set up/);
    await profile.click();
    const profiles = page.getByRole("menu", { name: "Profiles" });
    await expect(profiles.getByRole("menuitemradio", { checked: true })).toContainText(USER);
    await expect(profiles.getByRole("menuitem", { name: "Add another account / business" })).toBeVisible();
    await page.keyboard.press("Escape");

    // No sidebar for signed-in pages: the links are listed once, in the bar.
    await expect(page.getByRole("complementary")).toHaveCount(0);
    await expect(page.locator("aside")).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/top-bar-1440.png` });

    await account.click();
    const menu = page.getByRole("menu", { name: "Account" });
    await expect(menu).toContainText(NAME);
    await expect(menu).toContainText(USER);
    await expect(menu.getByRole("menuitem", { name: /^AI: / })).toHaveAttribute("href", "/meta-models");
    await page.screenshot({ path: `${SHOTS}/account-menu-1440.png` });
    // Sign out goes to Microsoft's sign-out and back to the site (the test sign-in helper signs in again on load).
    await menu.getByRole("menuitem", { name: "Sign out of this one" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("the footer on every signed-in page", async ({ page }) => {
    for (const route of ["/", "/review", "/files", "/settings", "/reports"]) {
      await page.goto(route);
      await expect(page.getByRole("navigation", { name: "Main" }), route).toBeVisible();
      const about = page.getByRole("navigation", { name: "About" });
      for (const [name, href] of [
        ["How it works", "/how-it-works"],
        ["Help and guides", "/help"],
        ["Privacy", "/privacy"],
        ["Meta models at work", "/models"],
        ["For judges", "/judges"],
      ] as const) {
        await expect(about.getByRole("link", { name, exact: true }), `${route} ${name}`).toHaveAttribute("href", href);
      }
      await expect(about.getByRole("link", { name: "Contact" })).toHaveAttribute("href", /^mailto:/);
      await expect(page.getByRole("contentinfo")).toContainText("Accnomos version 0.1.0");
    }
    await page.getByRole("navigation", { name: "About" }).getByRole("link", { name: "Help and guides" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Help and guides" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/footer-help-1440.png`, fullPage: true });
  });

  test("phones: a compact drawer, no sidebar, the same name and footer", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator("aside")).toHaveCount(0);
    await page.getByRole("button", { name: "Menu" }).click();
    const drawer = page.getByRole("dialog", { name: "Menu" });
    await expect(drawer.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Invoices" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/drawer-390.png` });
    await drawer.getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("button", { name: new RegExp(`^Account: ${USER}`) })).toBeVisible();
  });

  test("a normal user has no accountant portal in the menus; /accountant has its own small shell", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Accountant portal" })).toHaveCount(0);
    await page.getByRole("button", { name: /^Account: / }).click();
    await expect(page.getByRole("menu", { name: "Account" }).getByRole("menuitem", { name: "Accountant portal" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByLabel("Page name").fill("accountant");
    await expect(page.getByRole("dialog").getByRole("link")).toHaveCount(0);
    await page.keyboard.press("Escape");

    // Reached directly (from the public Accountants page): no business menu, the accountant's name and sign out.
    await page.goto("/accountant");
    await expect(page.getByRole("heading", { level: 1, name: "Accountant portal" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Sections" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: new RegExp(`^Account: ${USER}`) })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "About" })).toBeVisible();
  });

  test("Settings › Files & backups: Back up now writes a dated full backup with progress, lists it and checks it", async ({ page, runtime }) => {
    await page.goto("/settings");
    const panel = await settingsTab(page, "Files & backups");
    const full = panel.getByRole("region", { name: "Full backups" });
    await expect(full.getByText("No full backups yet.")).toBeVisible();
    await full.getByRole("button", { name: "Back up now" }).click();
    await expect(full.getByRole("status")).toContainText(/Backed up to Accnomos Backups\/\d{4}-\d{2}-\d{2}-\d{4}/);
    const list = full.getByRole("list", { name: "Full backups" });
    await expect(list.getByRole("listitem")).toHaveCount(1);
    const files = await runtime.files();
    const folder = files.find((f) => /^Accnomos Backups\/[^/]+\/manifest\.json$/.test(f))!.split("/").slice(0, 2).join("/");
    for (const name of ["books-system.zip", "books-system.zip.sha256", "documents-index.json", "RESTORE.txt", "manifest.json"]) {
      expect(files, name).toContain(`${folder}/${name}`);
    }
    await list.getByRole("button", { name: /^Check / }).click();
    await expect(list.getByRole("status")).toContainText(/Checksum and all \d+ files match/);
    await full.getByText("How to restore a backup").click();
    await expect(full).toContainText("Type RESTORE to go ahead");
    await page.screenshot({ path: `${SHOTS}/back-up-now-settings.png`, fullPage: true });
    // The audit line (full_backup_created) is checked in services/runtime/tests/test_full_backup_previous_files.py.
  });

  test("Files: Back up now is there too", async ({ page }) => {
    await page.goto("/files");
    const full = page.getByRole("region", { name: "Full backups" });
    await full.getByRole("button", { name: "Back up now" }).click();
    await expect(full.getByRole("list", { name: "Full backups" }).getByRole("listitem")).toHaveCount(1);
  });

  test("earlier files: Home shows the count, the list asks first, and only the ticked ones are read", async ({ page, runtime, request }) => {
    // Two documents put in the books folders by hand, never read: a receipt in 01 Receipts and one in Needs a look.
    const png = await runtime.goldPng();
    for (const path of ["01 Receipts/2025-03/old receipt.png", "02 Needs a look/scan from the van.png"]) {
      const put = await request.put(`${RUNTIME_URL}/__test/graph/v1.0/me/drive/special/approot:/${path}:/content`, {
        data: png,
        headers: { "Content-Type": "image/png" },
      });
      expect(put.ok()).toBeTruthy();
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const notice = page.getByRole("region", { name: "2 earlier files in your OneDrive not read yet" });
    await expect(notice).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/previous-files-home.png` });
    await notice.getByRole("link", { name: "See the list" }).click();
    await expect(page).toHaveURL(/\/files#previous-files$/);

    const section = page.getByRole("region", { name: "Earlier files not read yet" });
    const list = section.getByRole("list", { name: "Earlier files" });
    await expect(list.getByRole("checkbox")).toHaveCount(2);
    expect(await runtime.files()).toContain("01 Receipts/2025-03/old receipt.png"); // nothing moved yet
    await list.getByRole("checkbox", { name: /scan from the van/ }).uncheck();
    await page.screenshot({ path: `${SHOTS}/previous-files-list.png` });
    await section.getByRole("button", { name: "Read the ticked files (1)" }).click();
    await expect(section.getByRole("status")).toContainText("1 file read: each is a card in Review");
    await expect(list.getByRole("checkbox")).toHaveCount(1); // the one left unticked is still offered

    await section.getByRole("button", { name: "Leave them" }).click();
    await expect(section.getByText("No earlier files waiting.")).toBeVisible();

    await page.goto("/review");
    await expect(page.getByRole("main")).toContainText("Novex");
    await page.goto("/");
    await expect(page.getByRole("region", { name: /earlier files? in your OneDrive/ })).toHaveCount(0);
  });

  test("the AI line names Meta's Muse models in plain words and links to /meta-models", async ({ page }) => {
    await page.addInitScript(() =>
      window.localStorage.setItem("accnomos.ai", JSON.stringify({ mode: "local", baseUrl: "http://192.168.1.176:11434", model: "muse-glimmer:30b" })),
    );
    await page.goto("/");
    await page.getByRole("button", { name: /^Account: / }).click();
    const ai = page.getByRole("menu", { name: "Account" }).getByRole("menuitem", { name: /^AI: / });
    await expect(ai).toHaveText("AI: Meta Muse models on your own computer");
    await expect(ai).not.toContainText("Glimmer");
    await ai.click();
    await expect(page).toHaveURL(/\/meta-models$/);
    await expect(page.getByRole("heading", { level: 1, name: "Meta models at work" })).toBeVisible();
  });
});

test.describe("the accountant", () => {
  test.beforeEach(async ({ page, runtime }) => {
    await runtime.reset("accountant");
    await signIn(page);
    await createBooksFolder(page);
  });

  test("once the portal lists shared books, Accountant portal appears in this account's menu", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/accountant");
    await expect(page.getByRole("list", { name: "Your clients" }).getByRole("article")).toHaveCount(2);
    await page.screenshot({ path: `${SHOTS}/accountant-shell-1440.png` });
    await page.goto("/");
    await page.getByRole("button", { name: /^Account: / }).click();
    await page.getByRole("menu", { name: "Account" }).getByRole("menuitem", { name: "Accountant portal" }).click();
    await expect(page).toHaveURL(/\/accountant$/);
  });

  test("a silent Microsoft token that times out: one interactive try, then a plain message and Try again", async ({ page }) => {
    await page.goto("/accountant");
    await expect(page.getByRole("list", { name: "Your clients" }).getByRole("article")).toHaveCount(2);
    await page.evaluate(() => window.localStorage.setItem("accnomos.test.msal-timeout", "1"));
    await page.reload();
    const note = page.getByRole("alert").filter({ hasText: "Microsoft didn't answer in time" });
    await expect(note).toBeVisible();
    await expect(note).toContainText("Try again; if it keeps happening, sign in again.");
    await expect(page.getByRole("main")).not.toContainText("MSAL");
    await expect(page.getByRole("main")).not.toContainText("timed_out");
    expect(Number(await page.evaluate(() => window.localStorage.getItem("accnomos.test.msal-redirects")))).toBeGreaterThanOrEqual(1);
    await expect(note.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/connect?next=%2Faccountant");
    await page.screenshot({ path: `${SHOTS}/msal-timeout.png` });

    // Microsoft answers again: Try again loads the clients without leaving the page.
    await page.evaluate(() => window.localStorage.removeItem("accnomos.test.msal-timeout"));
    await note.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("list", { name: "Your clients" }).getByRole("article")).toHaveCount(2);
  });
});

test.describe("the sign-in check", () => {
  test("MSAL v5's leftover keys after a sign-out are not a sign-in", async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("msal.version", "5.26.0");
      window.localStorage.setItem("msal.3.account.keys", "[]");
      window.localStorage.setItem("msal.00000000-test.active-account-filters", "{}");
    });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Site" })).toBeVisible(); // the public site
  });

  test("a sign-in MSAL can no longer read keeps the top bar and says Sign in again (the live-site bug)", async ({ page }) => {
    // MSAL v5's account list is still there, but MSAL itself has no account (its session-cookie key is gone).
    await page.addInitScript(() => window.localStorage.setItem("msal.3.account.keys", '["msal.3|gone"]'));
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/review");
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.locator("aside")).toHaveCount(0);
    await expect(page.getByRole("banner").getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/connect?next=%2Freview");
    await expect(page.getByRole("navigation", { name: "About" })).toBeVisible();
  });
});
