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
