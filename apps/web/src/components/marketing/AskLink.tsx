"use client";

import { openChat } from "@/lib/public-site";

/** Opens the "Ask about Accnomos" chat from inside a page. */
export default function AskLink() {
  return (
    <button
      type="button"
      onClick={() => openChat()}
      className="rounded-xl bg-ink px-5 py-3 text-base font-extrabold text-ground hover:bg-teal-dark"
    >
      Ask about Accnomos
    </button>
  );
}
