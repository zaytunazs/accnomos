import { statSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { createBooksFolder, DEMO_DAY, expect, pickVatPeriod, signIn, test } from "./fixtures";

/**
 * docs/DEMO.md on stage, step by step, in test mode (`pnpm run e2e:demo` writes the shots): the runtime's "today" is the stage date
 * (4 Nov 2026, the `demo` seed), the stub AI reads apps/web/public/sample-receipt.png, mail goes to the fake sender.
 * Step n is row n of the script table; each asserts the words the script quotes, saves
 * docs/submission/shots/<nn>-<step>[-phone].png for docs/submission/VIDEO_SCRIPT.md and logs its time.
 * Steps that need the real world (HMRC, the Android app) are skipped with the reason.
 */

const WEB = path.resolve(__dirname, "..");
// Only `pnpm run e2e:demo` writes into docs/ (the shots carry real timestamps, so every run differs a little).
const SHOTS = process.env.E2E_DEMO_SHOTS === "1" ? path.resolve(WEB, "../../docs/submission/shots") : null;
const RECEIPT = path.join(WEB, "public/sample-receipt.png");
const SHOT_LIMIT = 400 * 1024;

const VIEWPORTS = [
  { name: "desktop", suffix: "", use: { viewport: { width: 1280, height: 800 } } },
  { name: "phone", suffix: "-phone", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
] as const;

/** The amount of one box of the live 9-box return on /vat: a table row on desktop, a card per box on the phone. */
function box(page: Page, phone: boolean, n: number, label: string) {
  const values = page.getByRole("region", { name: /Your return/ }).getByLabel("VAT box values");
  return phone
    ? values.getByRole("listitem").filter({ hasText: `Box ${n} · ${label}` }).locator("p").nth(1)
    : values.getByRole("row").filter({ hasText: label }).getByRole("cell").nth(2);
}

for (const vp of VIEWPORTS) {
  test.describe(`demo · ${vp.name}`, () => {
    test.use(vp.use);

    test("docs/DEMO.md, every step in order", async ({ page, runtime }) => {
      const phone = vp.name === "phone";
      const times: string[] = [];
      const started = Date.now();

      /** Row `n` of the DEMO.md script; `slug` names its screenshot. */
      async function step(n: number, slug: string, title: string, body: () => Promise<void>) {
        const t0 = Date.now();
        await test.step(`${n} · ${title}`, async () => {
          await body();
          const name = `${String(n).padStart(2, "0")}-${slug}${vp.suffix}.png`;
          const file = SHOTS ? path.join(SHOTS, name) : test.info().outputPath(name);
          await page.screenshot({ path: file, scale: "css", animations: "disabled", caret: "hide" });
          expect(statSync(file).size, `${path.basename(file)} is over 400 kB`).toBeLessThan(SHOT_LIMIT);
        });
        times.push(`${n} ${slug} ${((Date.now() - t0) / 1000).toFixed(1)} s`);
      }

      // "Set up before you go on": Connect done once, 00 Inbox empty, JM Trading Ltd imported from Outlook, Get set up dismissed.
      await runtime.reset("demo");
      await signIn(page, DEMO_DAY);
      await createBooksFolder(page);
      await page.goto("/contacts");
      // Import from Outlook now has a review step: see who will be added, tick "also add new", then confirm.
      await page.getByRole("button", { name: "Import from Outlook" }).first().click();
      await page.getByRole("checkbox", { name: "Also add Outlook entries that are not in your books (as customers)" }).check();
      await page.getByRole("button", { name: "Confirm import" }).click();
      await expect(page.getByRole("status")).toContainText(/\d+ added/); // JM Trading Ltd and the seeded suppliers
      await page.goto("/");
      await page.getByRole("region", { name: "Get set up" }).getByRole("button", { name: "Dismiss" }).click();

      await step(1, "home", "Home", async () => {
        await expect(page.getByRole("heading", { level: 1, name: "Good morning, Sam" })).toBeVisible();
        await expect(page.getByText("Wednesday 4 November")).toBeVisible();
        await expect(page.getByText("SAMPLE — FICTIONAL COMPANY")).toHaveCount(0); // signed in: the account's own, empty books
        if (!phone) {
          // Signed in, the AI line is in the menu bar's Account menu (ProfileMenu.tsx), not a sidebar.
          await page.getByRole("button", { name: /^Account: / }).click();
          await expect(page.getByRole("menu", { name: "Account" }).getByText("AI: stub answers (test mode)")).toBeVisible();
          await page.keyboard.press("Escape");
        }
      });

      await step(2, "files", "Files: 00 Inbox … 07 Reports and _System", async () => {
        await page.goto("/files");
        const tree = page.getByRole("list").filter({ hasText: "00 Inbox" }).first();
        for (const name of ["00 Inbox", "07 Reports"]) await expect(tree.getByText(name, { exact: true })).toBeVisible();
        await tree.getByText("rules, audit log, ledger events · show").click();
        await expect(tree.getByText("Ledger", { exact: true })).toBeVisible();
        await expect(page.getByRole("link", { name: "Open in OneDrive" })).toBeVisible();
      });

      await step(3, "choose-ai", "Connect → Choose your AI → Test connection", async () => {
        await page.goto("/connect/ai");
        await expect(page.getByRole("heading", { name: "Choose how Meta AI runs your books" })).toBeVisible();
        await expect(page.getByRole("button", { name: /^On my own machine/ })).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByRole("button", { name: /^My own Meta API key/ })).toBeVisible();
        await page.getByRole("button", { name: "Test connection" }).click();
        await expect(page.getByRole("status")).toContainText("Connected · accnomos-test-stub"); // live: the Glimmer model's name
      });

      await step(4, "scan", "Review → Add a receipt → Scan 00 Inbox now", async () => {
        await page.goto("/review");
        await expect(page.getByText("No receipts waiting")).toBeVisible();
        // "Add a receipt" opens the file picker: the presenter picks sample-receipt.png from Downloads.
        await page.locator('input[type="file"]').first().setInputFiles(RECEIPT);
        await expect(page.getByText("1 file added to 00 Inbox. Press “Scan 00 Inbox now”.")).toBeVisible();
        await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
        await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("1 new proposal");
      });

      const card = page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" });
      await step(5, "proposal", "The proposal card: source, checks, verifier, the document", async () => {
        await expect(card).toContainText("Read by Glimmer 30B on your machine");
        await expect(card).toContainText("2 Nov 2026");
        await expect(card).toContainText("GB 882431902 ✓");
        await expect(card).toContainText("£43.25 · £8.65 · £51.90");
        await expect(card).toContainText("VAT to reclaim £8.65");
        await expect(card).toContainText("Why: 2 lines, totals add up (43.25 + 8.65 = 51.90)");
        await expect(card).toContainText("Verifier agrees · all 6 fields match");
        await expect(card).toContainText(/checks by code: (\d+) of \1 passed/);
        // The document: test mode does not crop (CROP_MODE=off), so it shows the file as read.
        await card.getByRole("button", { name: /^Open the document for Novex Office Supplies Ltd/ }).click();
        const doc = page.getByRole("dialog", { name: /^Document: Novex Office Supplies Ltd/ });
        await expect(doc).toContainText("Read as it arrived: not cropped.");
        await doc.getByRole("button", { name: /^Close/ }).click();
        await card.evaluate((el) => el.scrollIntoView({ block: "start" }));
      });

      await step(6, "approve", "Always do this for Novex Office Supplies Ltd → Approve (post to books)", async () => {
        await card.getByRole("checkbox", { name: "Always do this for Novex Office Supplies Ltd" }).check();
        const approve = card.getByRole("button", { name: "Approve Novex Office Supplies Ltd · £51.90 and post to books" });
        await expect(approve).toHaveText("Approve (post to books)");
        const suffix = approve.locator("span", { hasText: "(post to books)" });
        await (phone ? expect(suffix).toBeHidden() : expect(suffix).toBeVisible()); // the phone shows "Approve" only
        await approve.click();
        await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText(
          "Approved · Autopilot will do this for Novex Office Supplies Ltd next time · U to undo",
        );
        await expect(page.getByText("No receipts waiting")).toBeVisible();
      });

      await step(7, "vat", "VAT return: Oct–Dec 2026 · current period; Box 4 £8.65, Box 7 £43", async () => {
        await page.goto("/vat");
        const picker = page.getByRole("radiogroup", { name: "VAT period" });
        await expect(picker.getByRole("radio", { name: /^Oct–Dec 2026/ }).first()).toContainText("current period · 1 entry");
        const region = page.getByRole("region", { name: /Your return/ });
        await expect(region).toContainText("Your return · Oct–Dec 2026 (current period)");
        await pickVatPeriod(page, "Jul–Sep 2026"); // zero on a fresh account
        await expect(box(page, phone, 4, "VAT reclaimed on purchases")).toHaveText("£0.00");
        await expect(box(page, phone, 7, "Total purchases excluding VAT")).toHaveText("£0");
        await pickVatPeriod(page, "Oct–Dec 2026");
        await expect(box(page, phone, 4, "VAT reclaimed on purchases")).toHaveText("£8.65");
        await expect(box(page, phone, 7, "Total purchases excluding VAT")).toHaveText("£43"); // whole pounds
        await expect(region).toContainText("£8.65 to reclaim");
        await region.getByLabel("VAT box values").evaluate((el) => el.scrollIntoView({ block: "start" }));
      });

      await test.step("8 · Connect to HMRC (sandbox) → Submit to HMRC (sandbox)", (s) =>
        s.skip(true, "needs HMRC's sandbox and the relay: test mode has neither and blocks every request off 127.0.0.1 "
          + "(e2e/hmrc.spec.ts checks the card against a routed relay); on stage the presenter follows DEMO.md row 8"));

      await step(9, "books-xlsx", "Files → Rebuild Books.xlsx → Open", async () => {
        await page.goto("/files");
        await page.getByRole("button", { name: "Rebuild now" }).click();
        await expect(page.getByRole("status").filter({ hasText: "Books.xlsx rebuilt" })).toContainText("Books.xlsx rebuilt from your ledger events");
        // The Books.xlsx card's OneDrive link (off 127.0.0.1, so not followed here).
        await expect(page.getByRole("link", { name: /Open.*Books\.xlsx/ }).first()).toHaveAttribute("href", /Books\.xlsx/);
      });

      await step(10, "ask", "Ask: How much VAT have I reclaimed this quarter?", async () => {
        await page.goto("/ask");
        await page.getByLabel("Ask your books").fill("How much VAT have I reclaimed this quarter?");
        await page.getByRole("button", { name: "Ask", exact: true }).click();
        const answer = page.getByRole("article");
        await expect(answer).toContainText("Your net VAT (Box 5) for this quarter is £8.65 (HMRC repays you)");
        const keyNumbers = answer.getByRole("table", { name: "Key numbers" });
        await expect(keyNumbers.getByRole("row").filter({ hasText: "VAT reclaimed (Box 4)" })).toContainText("£8.65");
        await expect(answer.getByRole("list", { name: "Files used" })).toContainText("_System/Ledger/events/2026-11/");
        await expect(answer).toContainText("Numbers by code · explanation by accnomos-test-stub");
      });

      const action = page.getByRole("article", { name: "Proposed: Invoice" });
      await step(11, "invoice-card", "Ask: send a £100 invoice to JM Trading → the card", async () => {
        await page.getByLabel("Ask your books").fill("send a £100 invoice to JM Trading");
        await page.getByRole("button", { name: "Ask", exact: true }).click();
        await expect(action).toContainText("Proposed · Invoice · needs your OK", { ignoreCase: true });
        await expect(action).toContainText("JM Trading Ltd · emailed to accounts@jmtrading.example");
        await expect(action).toContainText("20% on £100.00");
        await expect(action).toContainText("Due 4 December 2026");
        await expect(action).toContainText("£120.00");
        await expect(action).toContainText("Create the invoice and email it to accounts@jmtrading.example?");
        expect(await runtime.sent()).toEqual([]); // nothing goes out before Approve
        await action.evaluate((el) => el.scrollIntoView({ block: "center" }));
      });

      await step(12, "invoice-sent", "Approve → INV-0001 sent", async () => {
        await action.getByRole("button", { name: "Approve" }).click();
        await expect(action.getByRole("status")).toContainText("✓ Invoice INV-0001 for £120.00 sent to accounts@jmtrading.example.");
        const [mail] = await runtime.sent(); // the fake sender: nothing leaves the runtime
        expect(mail.to).toBe("accounts@jmtrading.example");
        expect(mail.subject).toContain("INV-0001");
        expect(mail.attachments).toEqual(["INV-0001.pdf"]);
        await action.evaluate((el) => el.scrollIntoView({ block: "center" }));
      });

      await test.step("13 · Android: Review, VAT and the camera", (s) =>
        s.skip(true, "the Flutter app is not part of the web test mode; the phone run of this spec (390 px) is the fallback"));

      await step(14, "home-after", "Back to Home: the invoice is on the dashboard", async () => {
        await page.goto("/");
        const owed = page.getByRole("group", { name: "Owed to you" });
        await expect(owed).toContainText("£120");
        await expect(owed).toContainText("1 unpaid sale");
        // The sale is in Oct–Dec too: £20.00 output VAT less the £8.65 reclaimed.
        await expect(page.getByRole("region", { name: "Deadlines" })).toContainText("Box 5 £11.35 to pay (so far)");
        await expect(page.getByRole("region", { name: "Recent activity" })).toContainText("Invoice sent · INV-0001");
        await owed.evaluate((el) => el.scrollIntoView({ block: "start" }));
      });

      console.log(`demo · ${vp.name}: ${times.join(" · ")}`);
      console.log(`demo · ${vp.name}: total ${((Date.now() - started) / 1000).toFixed(1)} s`);
    });
  });
}
