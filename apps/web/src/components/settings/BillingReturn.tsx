"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function BillingReturn() {
  useEffect(() => {
    window.location.replace(`/settings${window.location.search}#plan-billing`);
  }, []);
  return (
    <p className="mx-auto max-w-xl p-6 text-sm text-muted">
      Opening <Link href="/settings#plan-billing" className="font-bold text-teal-dark underline underline-offset-2">Plan &amp; billing</Link>…
    </p>
  );
}
