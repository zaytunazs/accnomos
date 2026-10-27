import ExplainMore from "@/components/ExplainMore";
import JobsList from "@/components/jobs/JobsList";

export const metadata = { title: "Jobs · Accnomos" };

export default function JobsPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Jobs</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            Hours, labour and materials per job, and what is still to invoice. Staff and their rates are in Settings.
          </p>
        </div>
        <ExplainMore title="How jobs work" anchor="jobs">
          Timesheets, staff rates and job costs are plain code with no AI. Invoiced value uses each person’s current rate, so changing a rate restates past jobs.
        </ExplainMore>
      </div>
      <JobsList />
    </div>
  );
}
