import Link from "next/link";
import DemoLink from "@/components/marketing/DemoLink";
import JoinForm from "@/components/sign-up/JoinForm";

export const metadata = {
  title: "Get 3 months free · Accnomos",
  description: "Leave your email and we will set you up with 3 months free of Accnomos, bookkeeping for UK small businesses.",
};

/**
 * /join: the short page the social posts link to ("3 months free"). The neutral sign-up (components/sign-up/JoinForm,
 * POST /public/sign-up) in every build, with one line on what Accnomos is and the demo for anyone who wants to look
 * first. No launch, beta or waiting-list wording (e2e/submission-mode.spec.ts).
 */
export default function JoinPage() {
  return (
    <div className="mx-auto max-w-2xl py-4 text-ink">
      <h1 className="text-3xl font-extrabold tracking-tight">Accnomos: bookkeeping you only have to check</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-muted">
        For UK small businesses, sole traders, landlords and personal finances. The AI reads your receipts, invoices and
        bank lines and proposes each entry; nothing is posted until you approve it, and code works out the figures. Your
        books are files in your own OneDrive.
      </p>
      <div className="mt-6">
        <JoinForm source="/join" everyBuild />
      </div>
      <p className="mt-6 text-[15px] leading-relaxed">
        Want to look around first?{" "}
        <DemoLink className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">Try the demo</DemoLink>{" "}
        with fictional sample books, or read{" "}
        <Link href="/how-it-works" className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
          how each feature works
        </Link>
        .
      </p>
    </div>
  );
}
