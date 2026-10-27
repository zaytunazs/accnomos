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
        />
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
      </div>
      <LiveReview
        fallback={
          <>
            <ProposalCard proposal={proposal} />
            <NeedsALookCard />
            <VoiceNoteCard />
          </>
        }
      />
    </div>
  );
}
