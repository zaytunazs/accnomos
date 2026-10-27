import { Suspense } from "react";
import JobDetail from "@/components/jobs/JobDetail";

// Static export: job ids are only known in the browser, so the job is a query parameter (?id=…).
export default function JobPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <JobDetail />
    </Suspense>
  );
}
