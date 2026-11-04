/**
 * A calm "the AI is wording this" indicator: a thin brand-teal bar running along the top edge of the card it sits in
 * (the card needs `relative overflow-hidden`) and one short line of text. The figures around it are already final:
 * only the wording is still coming. Reduced motion: a still bar (globals.css .ai-working-bar).
 */
export default function AiWorking({ label }: { label: string }) {
  return (
    <>
      <span aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-[3px] overflow-hidden bg-teal/15">
        <span className="ai-working-bar block h-full w-2/5 rounded-full bg-teal" />
      </span>
      <p role="status" className="mt-2 flex items-center gap-2 text-[13px] font-semibold text-teal-dark">
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 20 20" fill="none" className="shrink-0">
          <path d="M10 2.5v3M10 14.5v3M2.5 10h3M14.5 10h3M5 5l1.8 1.8M13.2 13.2 15 15M5 15l1.8-1.8M13.2 6.8 15 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        {label}
      </p>
    </>
  );
}
