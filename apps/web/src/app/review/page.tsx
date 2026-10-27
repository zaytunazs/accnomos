import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import LiveReview from "@/components/review/LiveReview";

export const metadata = { title: "Review · Accnomos" };

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
                maths matches the rate (S 20%, R 5%, Z 0%); the VAT number has the right shape;
                it is not a duplicate of something already filed; it is in pounds sterling; the
                date is valid; and the reading is confident enough.
              </p>
              <p>
                The missing-VAT-number rule: when your business is VAT-registered and a purchase
                over £250 shows no VAT and no VAT number, code asks the books whether the supplier
                is VAT-registered. If the books have never seen them, the card asks you instead —
                “Is {"<supplier>"} VAT-registered? Over £250 they should give a VAT invoice” — with
                a tick for “isn’t VAT-registered”. The tick teaches “not registered”; a VAT number
                seen on an approved receipt teaches “registered”; undoing the approval takes the
                tick back; Contacts can change the stored answer any time.
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
      <LiveReview />
    </div>
  );
}
