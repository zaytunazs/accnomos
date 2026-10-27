"use client";

import type { ReactNode } from "react";
import { useSignedIn } from "@/lib/signed-in";

/** Renders its children (sample content) only once this device is known to be signed out. */
export default function SignedOutOnly({ children }: { children: ReactNode }) {
  return useSignedIn() === false ? <>{children}</> : null;
}
