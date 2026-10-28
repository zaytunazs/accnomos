import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { OUT_DIR } from "./env.mjs";

/**
 * The judged build (NEXT_PUBLIC_SUBMISSION_MODE unset or "1", lib/public-site.ts) shows nothing that looks
 * unfinished: no pre-launch words anywhere in the export (pages, RSC payloads, scripts). The pre-launch branch is
 * inlined away by next.config.ts, so its words are not even in the bundle.
 */
const FORBIDDEN = [/coming soon/i, /\bbeta\b/i, /launching/i, /early access/i];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = path.join(dir, name);
    return statSync(p).isDirectory() ? files(p) : /\.(html|txt|js|json|css)$/.test(name) ? [p] : [];
  });
}

test("the submission-mode build has no pre-launch words", () => {
  test.skip(process.env.NEXT_PUBLIC_SUBMISSION_MODE === "0", "pre-launch build");
  const root = path.resolve(import.meta.dirname, "..", OUT_DIR);
  const all = files(root);
  expect(all.some((f) => f.endsWith("index.html"))).toBe(true);
  const hits: string[] = [];
  for (const f of all) {
    const text = readFileSync(f, "utf8");
    for (const re of FORBIDDEN) {
      const m = re.exec(text);
      if (m) hits.push(`${path.relative(root, f)}: "${text.slice(Math.max(0, m.index - 40), m.index + 40)}"`);
    }
  }
  expect(hits).toEqual([]);
});
