"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AI_CONFIG_EVENT, AI_INFO_HREF, aiLabel, loadAiConfig } from "@/lib/ai-config";

/** The AI line's text, following Settings › AI in this tab and others. */
export function useAiLabel(): string {
  const [label, setLabel] = useState(() => aiLabel(null));
  useEffect(() => {
    const read = () => setLabel(aiLabel(loadAiConfig()));
    read();
    window.addEventListener(AI_CONFIG_EVENT, read);
    window.addEventListener("storage", read);
    return () => {
      window.removeEventListener(AI_CONFIG_EVENT, read);
      window.removeEventListener("storage", read);
    };
  }, []);
  return label;
}

/**
 * The sidebar's AI line, a link to /meta-models. Reads the same store `ChooseAi` writes
 * (`accnomos.ai`), so it names the real setup instead of always saying
 * Glimmer. Follows changes made in Settings in this tab (a custom event —
 * same-tab writes get no `storage` event) and in other tabs.
 */
export default function AiSidebarLabel() {
  const label = useAiLabel();
  return (
    <Link href={AI_INFO_HREF} className="flex items-center gap-2 text-sm font-semibold text-muted hover:text-teal-dark hover:underline">
      <span aria-hidden="true" className="h-2 w-2 rounded-full bg-teal" />
      {label}
    </Link>
  );
}
