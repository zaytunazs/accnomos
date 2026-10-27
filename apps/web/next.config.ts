import type { NextConfig } from "next";

// The PWA is a static site: all state lives in the browser (MSAL tokens, AI config) and the
// stateless runtime is called directly. Static export lets Plesk (or any host) serve it.
// The MSAL redirect page is the static file /auth/callback.html (no rewrite needed).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: false,
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
