import JobsList from "@/components/jobs/JobsList";

export default function JobsPage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Jobs</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Hours, labour and materials per job, and what is still to invoice. Staff and their rates are in Settings.
        </p>
      </div>
      <JobsList />
    </div>
  );
}
