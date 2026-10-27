"use client";

import { useEffect, useState } from "react";
import { ago, intakeOn, lastInboxCheck } from "@/lib/intake";

/** "Last inbox check: 4 min ago · 2 imported" when Outlook intake is on (this device's record); otherwise `children`. */
export default function LastInboxCheck({ children }: { children: React.ReactNode }) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => {
      if (!intakeOn()) return;
      const last = lastInboxCheck();
      setText(last ? `Last inbox check: ${ago(last.at)} · ${last.imported} imported` : "Outlook intake is on · no inbox check yet");
    });
  }, []);

  return <p className="text-[13px] font-medium text-muted">{text ?? children}</p>;
}
