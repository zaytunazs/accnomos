"use client";

import { useEffect } from "react";
import { ProblemCard } from "@/components/ErrorDetails";
import { parseRuntimeError } from "@/components/States";

/**
 * A page that crashed while rendering. When the crash came from the runtime,
 * the message carries its correlation id ("· ref …", see lib/runtime.ts
 * errorDetail) and it is shown so support can find the failing call.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  const info = parseRuntimeError(error.message);
  return (
    <ProblemCard
      title="Something went wrong"
      body={info.detail || "This page hit a problem. Try again, or head back home — nothing is lost."}
      reference={info.ref}
      detailLines={error.digest ? [`Error digest: ${error.digest}`] : []}
      onRetry={reset}
    />
  );
}
