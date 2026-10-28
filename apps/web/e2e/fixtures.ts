import { randomUUID } from "node:crypto";
import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";
import { RUNTIME_URL } from "./env.mjs";

/** The fake account in src/lib/msal-test.ts. */
export const USER = "sam@sambuilds.example";
export const GOLD = "001_standard"; // Novex Office Supplies Ltd, 14 Aug 2026: net £43.25, VAT £8.65, total £51.90

const RUNTIME_HEADERS = { "X-Graph-Token": "test-token", "X-Account-Kind": "personal", "X-User": USER };
/**
 * This worker's own fakes in the runtime (app/testmode.py keys them by X-Test-Tenant), so specs run in parallel.
 * Random per worker process: a second run that reuses the same runtime (reuseExistingServer) can't reset this one.
 */
const TENANT = `w${process.env.TEST_WORKER_INDEX ?? 0}-${randomUUID().slice(0, 8)}`;
const LOCAL = /^(https?|wss?):\/\/(127\.0\.0\.1|localhost)(:\d+)?\//;

/** Direct calls to the test-mode runtime, for arranging state a spec is not about. */
export class Runtime {
  constructor(private readonly request: APIRequestContext) {}

  /**
   * Empty the fake OneDrive and reseed; `seed: "bank"` also posts the entries evals/gold/bank/barclays.csv pays for;
   * `seed: "demo"` makes today DEMO_DAY for this worker and puts JM Trading Ltd in the Outlook address book;
   * `seed: "purchases"` posts Jun–Oct 2026 purchases with line items (services/runtime/app/sample_purchases.py).
   */
  async reset(seed?: "bank" | "demo" | "purchases"): Promise<void> {
    const r = await this.request.post(`${RUNTIME_URL}/__test/reset${seed ? `?seed=${seed}` : ""}`);
    expect(r.ok(), `POST /__test/reset -> ${r.status()}: is the runtime on ${RUNTIME_URL} in test mode?`).toBeTruthy();
  }

  async goldPng(file = GOLD): Promise<Buffer> {
    const r = await this.request.get(`${RUNTIME_URL}/__test/gold/${file}.png`);
    expect(r.ok()).toBeTruthy();
    return r.body();
  }

  async files(): Promise<string[]> {
    return (await (await this.request.get(`${RUNTIME_URL}/__test/state`)).json()).files;
  }

  /** A runtime call as the signed-in user; fails the test unless it answers 2xx. */
  async api<T = unknown>(method: "GET" | "POST" | "PUT", path: string, data?: unknown): Promise<T> {
    const r = await this.request.fetch(`${RUNTIME_URL}${path}`, { method, headers: RUNTIME_HEADERS, data });
    expect(r.ok(), `${method} ${path} -> ${r.status()}: ${await r.text()}`).toBeTruthy();
    return r.json();
  }

  /** One person (cost £25/h, charge £45/h), one job and `hours` on `date` against it. */
  async addHours(hours: number, date: string): Promise<{ staffId: string; jobId: string }> {
    const staff = await this.api<{ id: string }>("POST", "/staff", {
      name: "Alex Carter", role: "Joiner", hourly_rate_pence: 2500, charge_rate_pence: 4500,
    });
    const job = await this.api<{ id: string }>("POST", "/jobs", { name: "Kitchen refit, 12 Harbour Lane", site_address: "12 Harbour Lane, Bristol BS1 4RW" });
    await this.api("POST", "/timesheets", { staff_id: staff.id, job_id: job.id, date, hours, note: "First fix" });
    return { staffId: staff.id, jobId: job.id };
  }

  /** What the fake mail sender recorded (nothing leaves the runtime). */
  async sent(): Promise<{ to: string; subject: string; attachments: string[] }[]> {
    return (await (await this.request.get(`${RUNTIME_URL}/__test/state`)).json()).sent;
  }

  /** Write a file straight into the fake OneDrive (parent folders are created), as the user could by hand. */
  async putFile(path: string, text: string): Promise<void> {
    const put = await this.request.put(`${RUNTIME_URL}/__test/graph/v1.0/me/drive/special/approot:/${path}:/content`, {
      data: text,
      headers: { "Content-Type": "text/plain" },
    });
    expect(put.ok(), `PUT ${path} -> ${put.status()}`).toBeTruthy();
  }

  /** Put a gold receipt in 00 Inbox, as if the user had dropped it there in OneDrive. */
  async dropInInbox(file = GOLD): Promise<void> {
    const put = await this.request.put(`${RUNTIME_URL}/__test/graph/v1.0/me/drive/special/approot:/00 Inbox/${file}.png:/content`, {
      data: await this.goldPng(file),
      headers: { "Content-Type": "image/png" },
    });
    expect(put.ok()).toBeTruthy();
  }

  /** Drop a gold receipt in 00 Inbox, scan and approve it: one posted purchase in the books. */
  async postGold(file = GOLD): Promise<void> {
    await this.dropInInbox(file);
    const scan = await this.request.post(`${RUNTIME_URL}/books/scan`, { headers: { ...RUNTIME_HEADERS, "X-Autopilot": "off" } });
    expect(scan.ok(), await scan.text()).toBeTruthy();
    const [proposal] = (await scan.json()).proposals;
    expect(proposal?.status).toBe("proposed");
    const ok = await this.request.post(`${RUNTIME_URL}/books/approve/${proposal.id}`, { headers: RUNTIME_HEADERS, data: {} });
    expect(ok.ok(), await ok.text()).toBeTruthy();
  }
}

/** The runtime's pinned test-mode "today" (ACCNOMOS_TEST_TODAY), 09:00 in London. */
export const TODAY = new Date("2026-10-27T09:00:00Z");
/** docs/DEMO.md's stage date, the runtime's "today" after `runtime.reset("demo")`, 09:00 in London. */
export const DEMO_DAY = new Date("2026-11-04T09:00:00Z");

/**
 * Signed in with the fake account, AI pointed at the stub. Only fills keys a test has not set itself.
 * The browser clock starts at `today` (and runs on), so pages that use the device's date agree with the runtime.
 */
export async function signIn(page: Page, today: Date = TODAY): Promise<void> {
  await page.clock.install({ time: today });
  await page.addInitScript(
    ({ ai }) => {
      const put = (k: string, v: string) => {
        if (window.localStorage.getItem(k) === null) window.localStorage.setItem(k, v);
      };
      put("msal.accnomos-test.signedIn", "1");
      put("accnomos.ai", JSON.stringify(ai));
    },
    { ai: { mode: "local", baseUrl: `${RUNTIME_URL}/__test/ai`, model: "accnomos-test-stub" } },
  );
}

/** Onboarding step 1 through the UI: creates the folder tree and README.txt in the fake OneDrive. */
export async function createBooksFolder(page: Page): Promise<void> {
  await page.goto("/connect");
  await page.getByRole("button", { name: "Create my Accnomos folder" }).click();
  await expect(page.getByText("Your folder is ready.")).toBeVisible();
}

/** Settings tabs (Connection, AI, Automation, Business, Your data); open one and return its panel. */
export async function settingsTab(page: Page, name: "Connection" | "AI" | "Automation" | "Business" | "Your data") {
  await page.getByRole("tablist", { name: "Settings groups" }).getByRole("tab", { name, exact: true }).click();
  const panel = page.getByRole("tabpanel", { name });
  await expect(panel).toBeVisible();
  return panel;
}

/** Pick a VAT period on /vat by its label (e.g. "Jul–Sep 2026"); the picker defaults to the current one. */
export async function pickVatPeriod(page: Page, label: string): Promise<void> {
  const group = page.getByRole("radiogroup", { name: "VAT period" });
  const option = group.getByRole("radio", { name: label });
  await expect(option, `no VAT period option "${label}"`).toHaveCount(1);
  await option.click();
}

export const test = base.extend<{ runtime: Runtime; localOnly: void }>({
  // The page and the `request` fixture both carry the tenant, so the browser and Runtime see one fake OneDrive.
  extraHTTPHeaders: [async ({ extraHTTPHeaders }, use) => use({ ...extraHTTPHeaders, "X-Test-Tenant": TENANT }), { scope: "test" }],
  // Every test starts from an empty fake OneDrive (this worker's) and a freshly seeded mailbox.
  runtime: [
    async ({ request }, use) => {
      const runtime = new Runtime(request);
      await runtime.reset();
      await use(runtime);
    },
    { auto: true },
  ],
  // Every test: anything not on 127.0.0.1 (Microsoft, Graph, HMRC, Meta…) is blocked and fails the test.
  localOnly: [
    async ({ context }, use) => {
      const escaped: string[] = [];
      await context.route(
        (url) => !LOCAL.test(url.href),
        (route) => {
          escaped.push(route.request().url());
          return route.abort("blockedbyclient");
        },
      );
      await use();
      expect(escaped, "requests that tried to leave 127.0.0.1").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
