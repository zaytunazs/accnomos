"use client";

import Link from "next/link";
import { useSelfEmployed } from "@/lib/itsa";

/** Shown on /self-employment while Settings › "I am self-employed" is off (the page still works from a link). */
export default function SelfEmployedHint() {
  if (useSelfEmployed()) return null;
  return (
    <p className="text-sm text-muted">
      This page is in the menu once you turn on{" "}
      <Link href="/settings#settings-self-employed" className="font-bold text-teal-dark">I am self-employed</Link> in Settings.
    </p>
  );
}
