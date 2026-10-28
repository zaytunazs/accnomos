"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getClientContext, queryLink, type QuerySubjectKind } from "@/lib/accountant";

/** "Send a query about this" on a card, only while an accountant is in a client's books (lib/accountant.ts). */
export default function QueryThisLink({ kind, refId, label }: { kind: QuerySubjectKind; refId: string; label: string }) {
  const [inClient, setInClient] = useState(false);
  useEffect(() => {
    queueMicrotask(() => setInClient(getClientContext() !== null));
  }, []);
  if (!inClient) return null;
  return (
    <Link href={queryLink(kind, refId, label)} className="mt-2 inline-block text-sm font-bold text-teal-dark underline">
      Send a query about this
    </Link>
  );
}
