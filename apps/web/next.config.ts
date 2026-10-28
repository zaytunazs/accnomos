import type { NextConfig } from "next";

// The PWA is a static site: all state lives in the browser (MSAL tokens, AI config) and the
// stateless runtime is called directly. Static export lets Plesk (or any host) serve it.
// The MSAL redirect page is the static file /auth/callback.html (no rewrite needed).
const nextConfig: NextConfig = {
  output: "export",
  // e2e/build.mjs puts the test-mode export in its own folder, so it can never be mistaken for out/.
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
  trailingSlash: false,
  // Always inlined (as "" unless set), so a normal build folds the test-mode branches away and ships no fake sign-in.
  // NEXT_PUBLIC_SUBMISSION_MODE (default "1"): the judged build, with no pre-launch messaging; "0" brings back the
  // launch date, "get notified" and the testers' sign-in link (lib/public-site.ts). Inlined, so the other branch's
  // words are not in the bundle at all.
  env: {
    NEXT_PUBLIC_TEST_MODE: process.env.NEXT_PUBLIC_TEST_MODE ?? "",
    NEXT_PUBLIC_SUBMISSION_MODE: process.env.NEXT_PUBLIC_SUBMISSION_MODE ?? "1",
  },
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
