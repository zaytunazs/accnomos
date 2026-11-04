import { expect, test } from "./fixtures";
import { createBooksFolder, signIn } from "./fixtures";
import { RUNTIME_URL } from "./env.mjs";

// Sign out lands on the homepage (the public landing), never on a "Sign in to view" page; the logo is a link home.
test("sign out goes to the homepage, and the logo links home", async ({ page }) => {
  await page.goto("/");
  // Signed in once, without the helper's init script (which would sign in again on every load).
  await page.evaluate(
    ({ ai }) => {
      window.localStorage.setItem("msal.accnomos-test.signedIn", "1");
      window.localStorage.setItem("accnomos.ai", JSON.stringify(ai));
    },
    { ai: { mode: "local", baseUrl: `${RUNTIME_URL}/__test/ai`, model: "accnomos-test-stub" } },
  );
  await page.goto("/settings");
  const home = page.getByRole("link", { name: "Accnomos home" }).first();
  await expect(home).toHaveAttribute("href", "/");
  await page.getByRole("button", { name: /^Account: / }).first().click();
  await page.getByRole("menu", { name: "Account" }).getByRole("menuitem", { name: "Sign out of this one" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator("#hero-title")).toBeVisible();
  await expect(page.getByText(/sign in to view/i)).toHaveCount(0);
});

// Home never waits on the model: the cards and code's summary first, the AI's words swapped in after.
test("Home shows every card before the AI summary arrives", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();
  let release: () => void = () => {};
  const held = new Promise<void>((r) => (release = r));
  await page.route(
    (u) => u.origin === RUNTIME_URL && u.pathname === "/books/home" && u.searchParams.get("summary_ai") === "true",
    async (route) => {
      await held;
      await route.continue();
    },
  );
  await page.goto("/");
  await expect(page.locator("[data-home-summary]")).toBeVisible();
  await expect(page.getByText("Your AI is putting this into words")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Business snapshot" })).toBeVisible();
  release();
  await expect(page.getByText("Your AI is putting this into words")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator("[data-home-summary]")).toBeVisible();
});
