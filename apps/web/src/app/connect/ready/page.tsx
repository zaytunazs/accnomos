import ReadyPanel from "@/components/onboarding/ReadyPanel";

export const metadata = { title: "Your folder is ready · Accnomos" };

export default function ReadyPage() {
  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <p className="text-xs font-bold uppercase tracking-wider text-teal-dark">Step 4 of 4</p>
      <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-ink">You&apos;re connected</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        Your books live in your OneDrive and your assistants are set. Here&apos;s what happens next.
      </p>
      <ReadyPanel />
    </div>
  );
}
