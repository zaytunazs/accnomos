import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import MonthEnd from "@/components/month-end/MonthEnd";

export const metadata = { title: "Month-end · Accnomos" };

export default function MonthEndPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Month-end"
        description="One button works through the close checklist: it does what code can and turns everything that needs you into a card."
        action={
          <Explain title="How the month-end close works">
            <p>
              The close agent is code. It works through nine steps in order (inbox, bank, sales, purchases, payroll,
              VAT, checks, reports, lock) and shows each one as it finishes: what it checked, what it found and what
              it proposes.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>It posts nothing.</strong> Bank matches, payment reminders and closing the month are cards: nothing happens until you tap Approve.</li>
              <li><strong>Blocking items</strong> (a missing bank statement, documents still waiting, unreconciled lines, a draft invoice, an uncategorised balance) must be cleared before the month can be closed.</li>
              <li><strong>VAT</strong>: when the month ends a VAT period, the 9 boxes and the deadline are shown. Submitting stays on the VAT page.</li>
              <li><strong>After the close</strong>: a snapshot of the month&apos;s figures is recorded. If anything dated in the month changes later, you are told what changed, with the figures before and after, and offered a re-close.</li>
            </ul>
            <p>Your AI writes only the summary, and code checks every figure in it. Without an AI, code writes it.</p>
          </Explain>
        }
      />
      <MonthEnd />
    </div>
  );
}
