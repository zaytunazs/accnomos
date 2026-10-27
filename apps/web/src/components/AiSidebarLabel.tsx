"use client";

import { useEffect, useState } from "react";
import { AI_CONFIG_EVENT, aiLabel, loadAiConfig } from "@/lib/ai-config";

/**
 * The sidebar's AI line. Reads the same store `ChooseAi` writes
 * (`accnomos.ai`), so it names the real setup instead of always saying
 * Glimmer. Follows changes made in Settings in this tab (a custom event —
 * same-tab writes get no `storage` event) and in other tabs.
 */
export default function AiSidebarLabel() {
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

  return (
    <p className="flex items-center gap-2 text-sm font-semibold text-muted">
      <span aria-hidden="true" className="h-2 w-2 rounded-full bg-teal" />
      {label}
    </p>
  );
}
