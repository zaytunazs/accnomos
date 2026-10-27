import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import ProposalCard from "@/components/review/ProposalCard";
import NeedsALookCard from "@/components/review/NeedsALookCard";
import VoiceNoteCard from "@/components/review/VoiceNoteCard";
import LiveReview from "@/components/review/LiveReview";
import { proposal } from "@/lib/sample-review";

export const metadata = { title: "Review · Accnomos" };

const filters = [
  { label: "Proposed · 2", active: true, warn: false },
  { label: "Needs a look · 1", active: false, warn: true },
  { label: "Approved today · 6", active: false, warn: false },
];

export default function ReviewPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        <PageHeader
          title="Review"
          description="AI proposes · you approve · code posts. Nothing reaches your books until you tap Approve."
          action={
            <Explain title="What the checks mean">
              <p>
                Every proposal is read by AI, then checked by plain code — never by the model.
                The checks are: the receipt lines add up; net plus VAT equals the total; the VAT
                maths matches the rate (S 20%, R 5%, Z 0%); the VAT number has the right shape
                (and over £250 a VAT number must be present); it is not a duplicate of something
                already filed; it is in pounds sterling; the date is valid; and the reading is
                confident enough.
              </p>
              <p>
                Any failed check moves the card to <strong>Needs a look</strong> with the reason
                in plain English and a suggested fix. Nothing is posted until you decide.
              </p>
              <p>
                When every check passes, a second model reads the same image again without seeing
                the first answer, and code compares six fields: supplier, VAT number, date, net,
                VAT and total. Any disagreement also means <strong>Needs a look</strong>, with
                both readings side by side for you to compare. Neither the model nor the code
                picks a winner.
              </p>
              <p>
                The “Why” line on each card is composed by code (“Checker, code”). There is no
                separate AI reviewer in the pipeline.
              </p>
            </Explain>
          }
        />
      </div>
      <LiveReview
        fallback={
          <>
            {/* The sample's counts: signed in, LiveReview shows how many are really waiting. */}
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filter reviews">
              {filters.map((filter) =>
                filter.warn ? (
                  <span
                    key={filter.label}
                    className="flex h-11 items-center whitespace-nowrap rounded-full border border-warn-border bg-warn-bg px-4 text-[14px] font-bold text-warn-ink"
                  >
                    {filter.label}
                  </span>
                ) : (
                  <span
                    key={filter.label}
                    className={`flex h-11 items-center whitespace-nowrap rounded-full border px-4 text-[14px] font-bold ${
                      filter.active
                        ? "border-teal bg-teal-tint text-teal-dark"
                        : "border-border bg-white text-muted"
                    }`}
                  >
                    {filter.label}
                  </span>
                ),
              )}
            </div>
            <ProposalCard proposal={proposal} />
            <NeedsALookCard />
            <VoiceNoteCard />
          </>
        }
      />
    </div>
  );
}
