// Summarise the axe reports a11y.spec.ts leaves in test-results/*/axe.json: one line per rule, the pages it hit.
// Usage: node scripts/axe-summary.mjs [--all]   (default: serious and critical only)
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const all = process.argv.includes("--all");
const rules = new Map();
for (const dir of readdirSync("test-results")) {
  const f = join("test-results", dir, "axe.json");
  if (!existsSync(f)) continue;
  const { path, violations } = JSON.parse(readFileSync(f, "utf8"));
  const state = dir.includes("signed-in") ? "in" : "out";
  for (const v of violations) {
    if (!all && !["serious", "critical"].includes(v.impact)) continue;
    const r = rules.get(v.id) ?? { impact: v.impact, help: v.help, pages: [], nodes: 0, targets: new Set() };
    r.pages.push(`${path} (${state})`);
    r.nodes += v.nodes.length;
    for (const n of v.nodes) r.targets.add(n.target.join(" "));
    rules.set(v.id, r);
  }
}
let total = 0;
for (const [id, r] of rules) {
  total += r.nodes;
  console.log(`[${r.impact}] ${id}: ${r.help} — ${r.nodes} nodes on ${r.pages.length} page states`);
  console.log(`    pages: ${r.pages.join(", ")}`);
  console.log(`    e.g. ${[...r.targets].slice(0, 6).join(" | ")}`);
}
console.log(`${rules.size} rules, ${total} nodes`);
