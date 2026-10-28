import { tmpdir } from "node:os";
import { join } from "node:path";

// Ports and URLs shared by the test-mode build (build.mjs), the static server (serve.mjs) and playwright.config.ts.
export const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
export const RUNTIME_PORT = Number(process.env.E2E_RUNTIME_PORT ?? 8781);
export const RELAY_PORT = Number(process.env.E2E_RELAY_PORT ?? 8789); // nothing listens: the HMRC spec routes it

export const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;
export const RUNTIME_URL = `http://127.0.0.1:${RUNTIME_PORT}`;
export const RELAY_URL = `http://127.0.0.1:${RELAY_PORT}`;
export const OUT_DIR = "out-e2e";
// The test-mode runtime's early-adopter list (EARLY_ACCESS_FILE): a temp file per runtime port, never in the repo.
export const EARLY_ACCESS_FILE = join(tmpdir(), `accnomos-e2e-early-access-${RUNTIME_PORT}.jsonl`);
