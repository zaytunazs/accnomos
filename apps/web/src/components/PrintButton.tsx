"use client";

/** A button that prints the page (or saves it as a PDF). Hidden on paper. */
export default function PrintButton({ className }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className={
        className ??
        "h-11 shrink-0 rounded-xl border border-border bg-white px-4 text-[15px] font-bold print:hidden"
      }
    >
      Print
    </button>
  );
}
