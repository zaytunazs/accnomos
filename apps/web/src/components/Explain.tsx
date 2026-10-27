"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

interface ExplainProps {
  /** Short label used in the button's accessible name and the drawer heading. */
  title: string;
  children: ReactNode;
}

/** A small "?" button that opens a plain-English explainer drawer. No dependencies, static-export safe. */
export default function Explain({ title, children }: ExplainProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!open) return;
    headingRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open ]);

  useEffect(() => {
    if (!open) buttonRef.current?.focus();
  }, [open ]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Explain: ${title}`}
        title={`Explain: ${title}`}
        onClick={() => setOpen(true)}
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-white text-[14px] font-extrabold text-teal-dark hover:bg-teal-tint"
      >
        <span aria-hidden="true">?</span>
      </button>
      {open && (
        <div className="fixed inset-0 z-50">
          <button
            type="button"
            aria-label="Close explanation"
            onClick={() => setOpen(false)}
            className="absolute inset-0 h-full w-full cursor-default bg-ink/40"
          />
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-labelledby={`${panelId}-heading`}
            className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-2xl border-t border-border bg-white p-5 pb-8 sm:inset-y-0 sm:right-0 sm:left-auto sm:w-[min(26rem,92vw)] sm:rounded-t-none sm:rounded-l-2xl sm:border-t-0 sm:border-l sm:p-6"
          >
            <div className="flex items-start justify-between gap-3">
              <h2
                ref={headingRef}
                id={`${panelId}-heading`}
                tabIndex={-1}
                className="text-lg font-extrabold tracking-tight outline-none"
              >
                {title}
              </h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close explanation"
                className="flex h-11 min-w-11 shrink-0 items-center justify-center rounded-xl border border-border px-3 text-[15px] font-bold hover:bg-ground"
              >
                Close
              </button>
            </div>
            <div className="mt-3 space-y-3 text-[15px] leading-7 text-ink">
              {children}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
