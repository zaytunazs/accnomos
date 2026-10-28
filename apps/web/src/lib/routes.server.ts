import fs from "node:fs";
import path from "node:path";

/**
 * Every page in this build ("/", "/invoices", "/jobs/job", …), read from src/app when the static export is made
 * (the root layout is a server component, so this runs at build time only and ships as a list). The menu bar
 * (lib/nav.ts) shows a link only when its page is here, so a page another branch has not landed yet never 404s.
 * Route groups "(x)" add no segment; dynamic "[x]" segments are left out (the static export has none in the menu).
 */
export function builtRoutes(): string[] {
  const app = path.join(process.cwd(), "src", "app");
  const out: string[] = [];
  const walk = (dir: string, segments: string[]) => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    if (entries.some((e) => e.isFile() && /^page\.(tsx|ts|jsx|js|mdx)$/.test(e.name))) {
      out.push(`/${segments.join("/")}`);
    }
    for (const e of entries) {
      if (!e.isDirectory() || e.name.startsWith("_") || e.name.startsWith("[") || e.name.startsWith("@")) continue;
      const group = e.name.startsWith("(") && e.name.endsWith(")");
      walk(path.join(dir, e.name), group ? segments : [...segments, e.name]);
    }
  };
  walk(app, []);
  return out.sort();
}
