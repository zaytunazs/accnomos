// Test-mode static export into out-e2e/ (never out/): fake Microsoft sign-in, Graph and AI via the test-mode
// runtime. Cross-platform stand-in for `NEXT_PUBLIC_TEST_MODE=1 ... next build`.
import { spawnSync } from "node:child_process";
import { OUT_DIR, RELAY_URL, RUNTIME_URL } from "./env.mjs";

const env = {
  ...process.env,
  NEXT_PUBLIC_TEST_MODE: "1",
  NEXT_PUBLIC_RUNTIME_URL: RUNTIME_URL,
  NEXT_PUBLIC_RELAY_URL: RELAY_URL,
  NEXT_PUBLIC_MS_CLIENT_ID: "",
  NEXT_DIST_DIR: OUT_DIR,
};
const r = spawnSync("pnpm", ["exec", "next", "build"], { stdio: "inherit", env, shell: process.platform === "win32" });
process.exit(r.status ?? 1);
