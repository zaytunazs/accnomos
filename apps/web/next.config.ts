import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    // MSAL v5 needs a redirect page with no app JS/router: serve the static bridge page at /auth/callback.
    return [{ source: "/auth/callback", destination: "/auth/callback.html" }];
  },
};

export default nextConfig;
