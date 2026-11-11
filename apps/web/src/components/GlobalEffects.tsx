"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { track } from "@/lib/analytics";
import { initSentry } from "@/lib/sentry";
import { useSignedIn } from "@/lib/signed-in";

/** Once per page: optional error reporting (only with NEXT_PUBLIC_SENTRY_DSN) and first-party page-view counts. */
export default function GlobalEffects() {
  const path = usePathname() ?? "/";
  const signedIn = useSignedIn();
  useEffect(() => {
    initSentry();
  }, []);
  useEffect(() => {
    if (signedIn === true && !path.startsWith("/admin")) track("page_view", { page: path });
  }, [signedIn, path]);
  return null;
}
