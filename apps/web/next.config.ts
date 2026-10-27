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
  env: { NEXT_PUBLIC_TEST_MODE: process.env.NEXT_PUBLIC_TEST_MODE ?? "" },
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
