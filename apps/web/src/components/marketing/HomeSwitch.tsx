"use client";

import type { ReactNode } from "react";
import { useSignedIn } from "@/lib/signed-in";

/** `/` shows the landing page until this device is known to be signed in (the static HTML is the landing page). */
export default function HomeSwitch({ landing, home }: { landing: ReactNode; home: ReactNode }) {
  return useSignedIn() === true ? <>{home}</> : <>{landing}</>;
}
