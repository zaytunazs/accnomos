import AuditLog from "@/components/admin/AuditLog";

export const metadata = { title: "Audit log · Admin · Accnomos", robots: { index: false, follow: false } };

export default function Page() {
  return <AuditLog />;
}
