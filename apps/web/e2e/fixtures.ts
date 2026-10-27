import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";
import { RUNTIME_URL } from "./env.mjs";

/** The fake account in src/lib/msal-test.ts. */
export const USER = "sam@sambuilds.example";
export const GOLD = "001_standard"; // Novex Office Supplies Ltd, 14 Aug 2026: net £43.25, VAT £8.65, total £51.90

const RUNTIME_HEADERS = { "X-Graph-Token": "test-token", "X-Account-Kind": "personal", "X-User": USER };
const LOCAL = /^(https?|wss?):\/\/(127\.0\.0\.1|localhost)(:\d+)?\//;

/** Direct calls to the test-mode runtime, for arranging state a spec is not about. */
export class Runtime {
  constructor(private readonly request: APIRequestContext) {}

  async reset(): Promise<void> {
    const r = await this.request.post(`${RUNTIME_URL}/__test/reset`);
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

  /** Drop a gold receipt in 00 Inbox, scan and approve it: one posted purchase in the books. */
  async postGold(file = GOLD): Promise<void> {
    const put = await this.request.put(`${RUNTIME_URL}/__test/graph/v1.0/me/drive/special/approot:/00 Inbox/${file}.png:/content`, {
      data: await this.goldPng(file),
      headers: { "Content-Type": "image/png" },
    });
    expect(put.ok()).toBeTruthy();
    const scan = await this.request.post(`${RUNTIME_URL}/books/scan`, { headers: { ...RUNTIME_HEADERS, "X-Autopilot": "off" } });
    expect(scan.ok(), await scan.text()).toBeTruthy();
    const [proposal] = (await scan.json()).proposals;
    expect(proposal?.status).toBe("proposed");
    const ok = await this.request.post(`${RUNTIME_URL}/books/approve/${proposal.id}`, { headers: RUNTIME_HEADERS, data: {} });
    expect(ok.ok(), await ok.text()).toBeTruthy();
  }
}

/** Signed in with the fake account, AI pointed at the stub. Only fills keys a test has not set itself. */
export async function signIn(page: Page): Promise<void> {
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

export const test = base.extend<{ runtime: Runtime; localOnly: void }>({
  // Every test starts from an empty fake OneDrive and a freshly seeded mailbox.
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
