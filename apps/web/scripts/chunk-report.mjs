// Which scripts one exported page loads, largest first, with a few markers to say what is inside each.
// Usage: node scripts/chunk-report.mjs out/privacy.html
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const page = process.argv[2] ?? "out/index.html";
const out = page.split("/")[0];
const html = readFileSync(page, "utf8");
const srcs = new Set([...html.matchAll(/"(\/_next\/static\/chunks\/[^"]+\.js)"/g)].map((m) => m[1]));
const MARKERS = ["PublicClientApplication", "msal", "react-dom", "createRoot", "MsalProvider", "useSyncExternalStore", "next/dist"];
const rows = [...srcs].map((s) => {
  const buf = readFileSync(join(out, s));
  const text = buf.toString("utf8");
  const found = MARKERS.filter((m) => text.includes(m));
  return { s, raw: buf.length, gz: gzipSync(buf, { level: 9 }).length, found };
});
rows.sort((a, b) => b.gz - a.gz);
for (const r of rows) console.log(`${(r.gz / 1000).toFixed(1).padStart(7)} kB gz ${(r.raw / 1000).toFixed(1).padStart(7)} kB  ${r.s}  ${r.found.join(",")}`);
