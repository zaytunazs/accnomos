import { Suspense } from "react";
import ReadyPanel from "@/components/onboarding/ReadyPanel";
import ConnectSteps from "@/components/connect/ConnectSteps";

export const metadata = { title: "Your folder is ready · Accnomos" };

export default function ReadyPage() {
  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <ConnectSteps current={4} />
      <h1 className="mt-4 text-3xl font-extrabold tracking-tight text-ink">You&apos;re connected</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        Your books live in your OneDrive and your assistants are set. Here&apos;s what happens next.
      </p>
      <Suspense fallback={<p className="mt-6 text-sm text-muted">Loading…</p>}>
        <ReadyPanel />
      </Suspense>
    </div>
  );
}
