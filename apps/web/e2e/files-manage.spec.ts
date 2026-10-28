import { RUNTIME_URL } from "./env.mjs";
import { USER, createBooksFolder, expect, signIn, test, type Runtime } from "./fixtures";

/**
 * Files page tools (services/runtime/app/routes_files.py) against the fake OneDrive: storage overview, Clean up,
 * search and filters, bulk move, rename, archive by year with undo, and backups (back up, check, restore with the
 * typed confirmation). Nothing is ever deleted: everything the app would remove ends up in _Trash.
 */

const OLD_RECEIPT = "01 Receipts/2024-08/2024-08-20 Toolstation £9.99.pdf";
const OLD_STATEMENT = "04 Bank statements/2025-01-31_starling.csv";

async function books(page: import("@playwright/test").Page, runtime: Runtime) {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex, 14 Aug 2026, £51.90: filed in 01 Receipts/2026-08 and linked to its ledger entry
  await runtime.putFile(OLD_RECEIPT, "old receipt");
  await runtime.putFile(OLD_STATEMENT, "Date,Amount\n2025-01-31,-9.99\n");
  await runtime.putFile("00 Inbox/copy of old receipt.pdf", "old receipt"); // the same bytes: a duplicate
}

test("Storage overview and Clean up: the duplicate copy moves to _Trash, the filed one stays", async ({ page, runtime }) => {
  await books(page, runtime);
  await page.goto("/files");
  const storage = page.getByRole("region", { name: "Storage" });
  await expect(storage.getByRole("list", { name: "Storage by folder" })).toContainText("01 Receipts");
  await expect(storage.getByRole("list", { name: "Storage by tax year" })).toContainText("2024-25");
  await expect(storage.getByRole("list", { name: "Storage by tax year" })).toContainText("2026-27");

  const dupes = storage.getByRole("list", { name: "Duplicate files" });
  await expect(dupes.getByRole("checkbox", { name: `Move to _Trash: ${OLD_RECEIPT}` })).toBeDisabled(); // the one kept
  await expect(dupes.getByRole("checkbox", { name: "Move to _Trash: 00 Inbox/copy of old receipt.pdf" })).toBeChecked();
  await storage.getByRole("button", { name: "Move 1 copy to _Trash" }).click();
  await expect(storage.getByRole("status")).toContainText("Moved 1 file to _Trash");
  const files = await runtime.files();
  expect(files).toContain("_Trash/2026-10-27/00 Inbox/copy of old receipt.pdf");
  expect(files).toContain(OLD_RECEIPT);
  await expect(page.getByRole("region", { name: "Storage" }).getByText("No duplicate files found.")).toBeVisible();
});

test("Find files: name, type and amount filters; Show in OneDrive; rename; bulk move keeps the Review link", async ({ page, runtime }) => {
  await books(page, runtime);
  await page.goto("/files");
  const find = page.getByRole("region", { name: "Find files" });
  const results = find.getByRole("list", { name: "Matching files" });

  await find.getByLabel("Name, folder or supplier").fill("toolstation");
  await expect(results.getByRole("listitem")).toHaveCount(1);
  await expect(results).toContainText(OLD_RECEIPT);
  await expect(results.getByRole("link", { name: /Show in OneDrive: 2024-08-20 Toolstation/ })).toHaveAttribute(
    "href",
    `https://onedrive.test.invalid/Accnomos/${OLD_RECEIPT}`,
  );

  // Amount: only documents linked to a ledger entry, by the entry's total.
  await find.getByRole("button", { name: "Clear filters" }).click();
  await find.getByLabel("Amount from (£)").fill("50");
  await find.getByLabel("Amount to (£)").fill("55");
  await expect(results.getByRole("listitem")).toHaveCount(1);
  await expect(results).toContainText("£51.90");
  await expect(results).toContainText("Novex");
  await find.getByLabel("Amount to (£)").fill("40");
  await expect(find.getByText("0 files found")).toBeVisible();

  await find.getByRole("button", { name: "Clear filters" }).click();
  await find.getByLabel("Type").selectOption("csv");
  await expect(results.getByRole("listitem")).toHaveCount(1);
  await expect(results).toContainText(OLD_STATEMENT);

  // Rename: characters OneDrive refuses become spaces, the extension stays.
  await find.getByRole("button", { name: "Clear filters" }).click();
  await find.getByLabel("Name, folder or supplier").fill("toolstation");
  await results.getByRole("button", { name: "Rename 2024-08-20 Toolstation £9.99.pdf" }).click();
  await results.getByLabel(/New name for/).fill("Toolstation: drill bits?");
  await results.getByRole("button", { name: "Save name" }).click();
  await expect(find.getByRole("status")).toContainText("Renamed to Toolstation drill bits.pdf");
  expect(await runtime.files()).toContain("01 Receipts/2024-08/Toolstation drill bits.pdf");

  // Bulk move the posted Novex receipt; Review's link to it still opens the moved file.
  await find.getByLabel("Name, folder or supplier").fill("novex");
  await expect(results.getByRole("listitem")).toHaveCount(1);
  await find.getByRole("checkbox", { name: "Select all shown (1)" }).check();
  await find.getByLabel("Move selected to").selectOption("07 Reports");
  await find.getByRole("button", { name: "Move 1 file" }).click();
  await expect(find.getByRole("status")).toContainText("Moved 1 file to 07 Reports");
  const files = await runtime.files();
  const moved = files.find((f) => f.startsWith("07 Reports/") && f.includes("Novex"));
  expect(moved, files.join("\n")).toBeTruthy();
  const [posted] = await runtime.api<{ file_path: string }[]>("GET", "/books/proposals?status=posted");
  expect(posted.file_path).toBe(moved);
});

test("Archive older years: preview, archive, undo; ledger events never move", async ({ page, runtime }) => {
  await books(page, runtime);
  const before = (await runtime.files()).filter((f) => f.startsWith("_System/Ledger/events/"));
  await page.goto("/files");
  const archive = page.getByRole("region", { name: "Archive older years" });
  const year = archive.getByLabel("Archive up to and including");
  await expect(year.locator("option", { hasText: "2024-25" })).toHaveCount(1);
  await expect(year.locator("option", { hasText: "2026-27" })).toHaveCount(0); // the year we are in
  await year.selectOption("2024-25");
  await archive.getByLabel(/Also save each year as one zip/).check();
  await archive.getByRole("button", { name: "Preview" }).click();
  const preview = archive.getByRole("region", { name: "Archive preview" });
  await expect(preview).toContainText(`${OLD_RECEIPT} → Archive/2024-25/${OLD_RECEIPT}`);
  await expect(preview).toContainText(`Archive/2024-25/${OLD_STATEMENT}`);
  await archive.getByRole("button", { name: "Archive 2 files" }).click();
  await expect(archive.getByRole("status")).toContainText("Archived 2 files and saved Archive/2024-25.zip");

  let files = await runtime.files();
  expect(files).toContain(`Archive/2024-25/${OLD_RECEIPT}`);
  expect(files).toContain("Archive/2024-25.zip");
  expect(files).not.toContain(OLD_RECEIPT);
  expect(files.filter((f) => f.startsWith("_System/Ledger/events/"))).toEqual(before);
  expect(files).toContain("_System/archive/map.json");

  // Search finds archived files too.
  const find = page.getByRole("region", { name: "Find files" });
  await find.getByRole("combobox", { name: "Archive", exact: true }).selectOption("archived");
  await expect(find.getByRole("list", { name: "Matching files" }).getByRole("listitem")).toHaveCount(3); // + the zip

  await archive.getByRole("button", { name: "Undo the archive up to 2024-25" }).click();
  await expect(archive.getByRole("status")).toContainText("Moved 2 files back");
  files = await runtime.files();
  expect(files).toContain(OLD_RECEIPT);
  expect(files).toContain(OLD_STATEMENT);
  expect(files).toContain("_Trash/2026-10-27/Archive/2024-25.zip"); // the zip is moved aside, never deleted
  await expect(archive.getByRole("list", { name: "Archive runs" })).toContainText("undone");

  // Audit lines carry the real clock, while test mode pins the runtime's "today": ask for the real date.
  const real = new Date().toISOString().slice(0, 10);
  const audit = await runtime.api<{ entries: { summary: string }[] }>("GET", `/audit?from=2026-10-01&to=${real}`);
  const said = audit.entries.map((e) => e.summary);
  expect(said).toContain("Archived 2 files up to 2024-25 into 2024-25 and zipped them");
  expect(said).toContain("Undid an archive run: 2 files moved back");
});

test("Backups: back up now, check it, restore refuses until RESTORE is typed", async ({ page, runtime, request }) => {
  await books(page, runtime);
  await runtime.putFile("_System/rules.json", '[{"match": {"supplier_regex": "Novex"}, "account": "5000 Materials"}]');
  await page.goto("/files");
  const panel = page.getByRole("region", { name: "Backups" });
  await expect(panel.getByText("No backups yet.")).toBeVisible();
  await panel.getByRole("button", { name: "Back up now" }).click();
  await expect(panel.getByRole("status").first()).toContainText("to Backups/accnomos-backup-2026-10-27.zip");
  const files = await runtime.files();
  expect(files).toContain("Backups/accnomos-backup-2026-10-27.zip");
  expect(files).toContain("Backups/accnomos-backup-2026-10-27.zip.sha256");

  const list = panel.getByRole("list", { name: "Backups" });
  await list.getByRole("button", { name: "Check accnomos-backup-2026-10-27.zip" }).click();
  await expect(list.getByText(/Checksum and all \d+ files match/)).toBeVisible();

  // Change a file after the backup, so restoring would replace it (today's copy goes to _Trash first).
  await runtime.putFile("_System/rules.json", "[]");
  await list.getByRole("button", { name: "Restore accnomos-backup-2026-10-27.zip" }).click();
  const restore = panel.getByRole("region", { name: "Restore preview" });
  await expect(restore).toContainText("Your books are not empty. Type RESTORE");
  const go = restore.getByRole("button", { name: "Restore", exact: true });
  await expect(go).toBeDisabled();
  await restore.getByRole("textbox").fill("restore");
  await expect(go).toBeDisabled();
  await restore.getByRole("textbox").fill("RESTORE");
  await go.click();
  await expect(panel.getByRole("status").first()).toContainText("Restored accnomos-backup-2026-10-27.zip: 0 files added, 1 replaced");
  const after = await runtime.files();
  expect(after.some((f) => /^_Trash\/2026-10-27\/restore-\d{6}\/_System\/rules\.json$/.test(f)), after.join("\n")).toBeTruthy();

  // The runtime refuses without the word too, not only the button.
  const refused = await request.post(`${RUNTIME_URL}/backups/restore`, {
    headers: { "X-Graph-Token": "test-token", "X-Account-Kind": "personal", "X-User": USER },
    data: { path: "Backups/accnomos-backup-2026-10-27.zip" },
  });
  expect(refused.status()).toBe(409);
  expect(await refused.text()).toContain("type RESTORE");
  await expect(panel.getByLabel("Keep the last")).toHaveValue("12");
  await panel.getByLabel("Keep the last").fill("3");
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  await expect(panel.getByRole("status").first()).toContainText("keep the last 3");
});

test.describe("Files tools at 360 px", () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test("Back up now and the search box fit on a small phone", async ({ page, runtime }) => {
    await books(page, runtime);
    await page.goto("/files");
    await expect(page.getByRole("region", { name: "Find files" })).toBeVisible();
    const button = page.getByRole("button", { name: "Back up now" });
    await button.scrollIntoViewIfNeeded();
    await expect(button).toBeInViewport();
    const box = await page.getByLabel("Name, folder or supplier").boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= 360).toBeTruthy();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  });
});
