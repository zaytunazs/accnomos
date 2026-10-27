import { deadlines } from "@/lib/sample-home";

export default function Deadlines() {
  return (
    <section aria-labelledby="deadlines-heading" className="flex flex-col gap-3">
      <h2
        id="deadlines-heading"
        className="text-lg font-extrabold tracking-tight"
      >
        Deadlines
      </h2>
      <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-3">
        {deadlines.map((d) => (
          <div
            key={d.title}
            className="flex items-center gap-3 rounded-2xl border border-border bg-white p-4"
          >
            <div
              aria-hidden="true"
              className={`flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-xl ${
                d.tinted ? "bg-teal-tint text-teal-dark" : "bg-ground text-muted"
              }`}
            >
              <span className="text-[11px] font-extrabold tracking-wide">
                {d.month}
              </span>
              <span className="text-xl font-extrabold leading-none">
                {d.day}
              </span>
            </div>
            <div className="min-w-0">
              <p className="text-[15px] font-bold leading-snug">{d.title}</p>
              <p className="mt-0.5 text-[13px] font-medium leading-snug text-muted">
                {d.sub}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
