// Pre-launch wording that the submission build (NEXT_PUBLIC_SUBMISSION_MODE unset or "1") must not show anywhere:
// "Early access / testers", "coming soon", "beta", "launching", a launch date, the early-adopter list.
// Shared by e2e/submission-mode.spec.ts (every rendered page) and, run as a script, CI's check of the production
// export, where the words must not be in any file at all (HTML, RSC payloads, JS chunks).
// Usage: node scripts/prelaunch-words.mjs [outDir]   (exits 1 and lists each hit)
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export const PRELAUNCH_WORDS = [
  /coming soon/i,
  /\bbeta\b/i,
  /\blaunch(?:ing|es)?\b/i,
  /early[ -]?access/i,
  /early[ -]?adopter/i,
  /early list/i,
  /\btesters\b/i,
];

/**
 * Non-Meta tools, engines and hardware that no public or judge-facing page may name (owner's rule, 29 Oct 2026): a
 * non-Meta fallback is "a local fallback model". Checked on every rendered page by e2e/submission-mode.spec.ts only,
 * not on the export's files: the JS keeps provider ids such as "baseten:" and "ollama:" to map them to Meta names.
 */
export const THIRD_PARTY_NAMES = [/whisper/i, /kokoro/i, /ollama/i, /vllm/i, /qwen/i, /comfyui/i, /\bdgx\b/i, /baseten/i];

/** Each match in `text` as a short quoted excerpt. */
export function prelaunchHits(text, words = PRELAUNCH_WORDS) {
  const hits = [];
  for (const re of words) {
    const g = new RegExp(re.source, "gi");
    for (const m of text.matchAll(g)) {
      hits.push(JSON.stringify(text.slice(Math.max(0, m.index - 40), m.index + m[0].length + 40)));
    }
  }
  return hits;
}

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? files(p) : /\.(html|txt|js|json|css|webmanifest)$/.test(name) ? [p] : [];
  });
}

// Run as a script (not imported by the spec; Playwright loads this file without import.meta).
if (/prelaunch-words\.mjs$/.test(process.argv[1] ?? "")) {
  const out = process.argv[2] ?? "out";
  const all = files(out);
  if (!all.some((f) => f.endsWith("index.html"))) {
    console.error(`${out}: no index.html; build first`);
    process.exit(2);
  }
  let bad = 0;
  for (const f of all) {
    for (const h of prelaunchHits(readFileSync(f, "utf8"))) {
      console.error(`${relative(out, f)}: ${h}`);
      bad++;
    }
  }
  console.log(`${all.length} files checked, ${bad} pre-launch phrase(s) found`);
  process.exit(bad ? 1 : 0);
}
