import LiveGoals from "@/components/goals/LiveGoals";

export const metadata = { title: "Goals · Accnomos", robots: { index: false, follow: false } };

export default function GoalsPage() {
  return <LiveGoals />;
}
