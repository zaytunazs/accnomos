import { activity } from "@/lib/sample-home";

export default function Activity() {
  return (
    <section
      aria-labelledby="activity-heading"
      className="rounded-2xl border border-border bg-white p-5"
    >
      <h2
        id="activity-heading"
        className="text-lg font-extrabold tracking-tight"
      >
        What the agents did today
      </h2>
      <ul className="mt-3 flex flex-col divide-y divide-border">
        {activity.map((item) => (
          <li key={`${item.time}-${item.actor}`} className="flex gap-3 py-3">
            <span
              aria-hidden="true"
              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                item.dot === "amber" ? "bg-amber" : "bg-teal"
              }`}
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm leading-6">
                <span className="font-bold tabular-nums">{item.time}</span>
                <span className="text-muted"> · </span>
                {item.text}
              </p>
            </div>
            <p className="shrink-0 text-right text-[13px] font-semibold text-muted">
              {item.actor}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
