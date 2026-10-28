import PageHeader from "@/components/PageHeader";
import ModelsAtWork from "@/components/models/ModelsAtWork";
import { evalHeadlines } from "@/lib/evals";

export const metadata = { title: "Meta models at work · Accnomos" };

export default function ModelsPage() {
  // Read from evals/runs/*/summary.json when the site is built: the numbers are the committed runs', not typed in.
  const evals = evalHeadlines();
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Meta models at work"
        description="Which Meta models read your documents and answer your questions, whether each is up right now, and how they scored on our test sets."
      />
      <ModelsAtWork evals={evals} />
    </div>
  );
}
