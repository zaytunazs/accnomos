// Minimal static host for the test-mode export, mapping /connect to connect.html as the production .htaccess does.
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { OUT_DIR, WEB_PORT } from "./env.mjs";

const root = resolve(OUT_DIR);
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain", ".woff2": "font/woff2",
  ".webmanifest": "application/manifest+json",
};

function resolveFile(urlPath) {
  const rel = normalize(decodeURIComponent(urlPath)).replace(/^([/\\])+/, "");
  const base = join(root, rel);
  if (!base.startsWith(root)) return null;
  // Next.js static export keeps each route's RSC prefetch payload at
  // `<route>/__next.<first>/<rest...>/__PAGE__.txt`, while the client asks for
  // `<route>/__next.<dotted-route>.__PAGE__.txt` (dots, as `next start` serves).
  // Map the dotted form onto the on-disk file so prefetches complete like prod.
  const m = /(^|[\\/])__next\.(.*)\.__PAGE__\.txt$/.exec(rel);
  if (m && m[2].length > 0) {
    const parts = m[2].split(".");
    const dir = m[1] ? rel.slice(0, m.index + m[1].length) : "";
    const mapped = join(root, dir, `__next.${parts[0]}`, ...parts.slice(1), "__PAGE__.txt");
    if (mapped.startsWith(root) && existsSync(mapped) && statSync(mapped).isFile()) return mapped;
  }
  for (const p of [base, `${base}.html`, join(base, "index.html")]) {
    if (existsSync(p) && statSync(p).isFile()) return p;
  }
  return null;
}

createServer((req, res) => {
  const path = new URL(req.url ?? "/", "http://x").pathname;
  const file = resolveFile(path);
  const status = file ? 200 : 404;
  const body = file ?? join(root, "404.html");
  res.writeHead(status, { "Content-Type": TYPES[extname(body)] ?? "application/octet-stream", "Cache-Control": "no-store" });
  createReadStream(body).pipe(res);
}).listen(WEB_PORT, "127.0.0.1", () => console.log(`serving ${root} on http://127.0.0.1:${WEB_PORT}`));
