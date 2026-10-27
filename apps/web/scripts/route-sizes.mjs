// First-load JS per route of the static export (Next 16 no longer prints sizes in `next build`).
// For every exported page: the scripts its HTML loads or preloads, summed raw and gzipped (what crosses the wire).
// Usage: node scripts/route-sizes.mjs [outDir] [--budget=250]   (budget in kB gzipped; exits 1 when a route is over)
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { gzipSync } from "node:zlib";

const args = process.argv.slice(2);
const out = args.find((a) => !a.startsWith("--")) ?? "out";
const budget = Number(args.find((a) => a.startsWith("--budget="))?.split("=")[1] ?? 250);

function pages(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "_next" || name === "auth" ? [] : pages(p);
    return name.endsWith(".html") ? [p] : [];
  });
}

const sizes = new Map();
function size(src) {
  if (!sizes.has(src)) {
    const buf = readFileSync(join(out, src));
    sizes.set(src, { raw: buf.length, gz: gzipSync(buf, { level: 9 }).length });
  }
  return sizes.get(src);
}

const kb = (n) => (n / 1000).toFixed(1);
const rows = pages(out)
  .map((file) => {
    const html = readFileSync(file, "utf8");
    const srcs = new Set(
      [...html.matchAll(/<script[^>]*\ssrc="([^"]+\.js)"|<link[^>]*as="script"[^>]*href="([^"]+\.js)"/g)].map((m) => m[1] ?? m[2]),
    );
    let raw = 0;
    let gz = 0;
    for (const s of srcs) {
      const z = size(s);
      raw += z.raw;
      gz += z.gz;
    }
    const route = "/" + relative(out, file).replace(/\.html$/, "").replace(/(^|\/)index$/, "");
    return { route: route === "/" ? "/" : route.replace(/\/$/, ""), files: srcs.size, raw, gz };
  })
  .sort((a, b) => a.route.localeCompare(b.route));

console.log(`| Route | Scripts | First-load JS (gzip) | Raw |\n|---|---:|---:|---:|`);
for (const r of rows) console.log(`| \`${r.route}\` | ${r.files} | ${kb(r.gz)} kB | ${kb(r.raw)} kB |`);
const over = rows.filter((r) => r.gz / 1000 > budget);
if (over.length) {
  console.error(`\nOver the ${budget} kB budget: ${over.map((r) => `${r.route} (${kb(r.gz)} kB)`).join(", ")}`);
  process.exit(1);
}
