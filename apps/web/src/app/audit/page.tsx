import LiveAudit from "@/components/audit/LiveAudit";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Audit trail · Accnomos" };

export default function AuditPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Audit trail"
        description="Everything done in your books, and who did it: you, or an agent working for you. Read from _System/audit in your OneDrive; nothing here can be edited. A correction is always a new entry."
      />
      <LiveAudit />
    </div>
  );
}
