import ConnectMicrosoft from "@/components/ConnectMicrosoft";
import ConnectSteps from "@/components/connect/ConnectSteps";
import Link from "next/link";
import TryDemo, { IfDemoAvailable } from "@/components/demo/TryDemo";

export const metadata = { title: "Connect your cloud · Accnomos", robots: { index: false, follow: false } };

export default function ConnectPage() {
  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <ConnectSteps current={1} />
      <h1 className="mt-4 text-3xl font-extrabold tracking-tight text-[#1B1F24]">Connect your cloud</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-[#4B5159]">
        Your books will live in a folder in your own OneDrive. Accnomos keeps nothing on its servers: sign in
        with Microsoft, and we create the folder in your account.
      </p>
      <ConnectMicrosoft />
      <IfDemoAvailable>
      <section aria-labelledby="try-demo" className="mt-8 rounded-2xl border border-[#E3E1D8] bg-white p-4">
        <h2 id="try-demo" className="text-[15px] font-extrabold text-[#1B1F24]">
          Just looking? Try the demo first
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-[#4B5159]">
          Two sandboxes, no sign-in needed: a fictional business&apos;s books, or a fictional household&apos;s own money
          (both labelled SAMPLE). Each resets after 2 hours and sends nothing anywhere. <Link href="/judges" className="font-bold text-[#3F2000] underline underline-offset-2">Judging? Start here</Link>.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <TryDemo label="Company demo — no sign-in" />
          <TryDemo kind="personal" next="/personal" label="Personal demo — no sign-in" variant="secondary" />
        </div>
      </section>
      </IfDemoAvailable>
    </div>
  );
}
