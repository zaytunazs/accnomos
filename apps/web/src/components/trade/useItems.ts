"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtItem } from "@/lib/runtime";

/** The live (not archived) products and services, for the item pickers. Empty while loading or if they cannot load. */
export function useItems(account: AccountInfo | null): RtItem[] {
  const [items, setItems] = useState<RtItem[]>([]);
  useEffect(() => {
    if (!account) return;
    let live = true;
    runtime.items(account).then((r) => live && setItems(r)).catch(() => live && setItems([]));
    return () => {
      live = false;
    };
  }, [account]);
  return items;
}
