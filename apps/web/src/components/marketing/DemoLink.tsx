"use client";

import { useState, type MouseEvent, type ReactNode } from "react";
import { startDemo } from "@/lib/demo";
import { DEMO_GUIDE } from "@/lib/public-site";

/**
 * "Try the demo": one click starts a demo sandbox (lib/demo.ts, no sign-in) and opens the judges' guide inside it,
 * with the demo bar. It is a plain link to the guide underneath, so without scripts, or when this server runs no
 * demos (the guide then says so), it still lands somewhere that explains. A modified click opens the guide as is.
 */
export default function DemoLink({ className, children = "Try the demo" }: { className: string; children?: ReactNode }) {
  const [busy, setBusy] = useState(false);

  async function open(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await startDemo();
    } catch {
      // The guide shows why a demo can't start (switched off, offline) and keeps its own Start button.
    }
    window.location.assign(DEMO_GUIDE); // a full load, so every page picks the demo session up
  }

  return (
    <a href={DEMO_GUIDE} onClick={open} aria-busy={busy || undefined} className={className}>
      {busy ? "Preparing the sample books…" : children}
    </a>
  );
}
