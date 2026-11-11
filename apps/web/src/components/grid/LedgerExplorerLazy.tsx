"use client";

import dynamic from "next/dynamic";

/** The ledger explorer loads AG Grid only when the page opens in the browser, keeping it out of the first load. */
const LedgerExplorer = dynamic(() => import("@/components/grid/LedgerExplorer"), {
  ssr: false,
  loading: () => <p className="text-sm text-muted">Opening the ledger explorer…</p>,
});

export default LedgerExplorer;
