"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

interface ExplainProps {
  /** Short label used in the button's accessible name and the drawer heading. */
  title: string;
  children: ReactNode;
}

/**
 * A small "?" button that opens a plain-English explainer drawer. No dependencies, static-export safe.
 * The drawer is a native modal <dialog>: the page behind is inert (Tab stays inside), Escape closes it, and focus
 * goes back to the "?" button — only after it was open, never on page load.
 */
export default function Explain({ title, children }: ExplainProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    const button = buttonRef.current;
    dialog.showModal();
    headingRef.current?.focus();
    const cancel = (e: Event) => {
      e.preventDefault(); // closed through state, so the dialog is never closed but mounted
      setOpen(false);
    };
    // Chrome may close without a cancelable "cancel" (a second Escape with no click between): follow it.
    const closed = () => setOpen(false);
    dialog.addEventListener("cancel", cancel);
    dialog.addEventListener("close", closed);
    return () => {
      dialog.removeEventListener("cancel", cancel);
      dialog.removeEventListener("close", closed);
      dialog.close();
      button?.focus({ preventScroll: true });
    };
  }, [open]);

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
        <dialog
          ref={dialogRef}
          id={panelId}
          aria-labelledby={`${panelId}-heading`}
          // Backdrop click. The padding is on the inner wrapper, so a click anywhere in the panel never lands on <dialog>.
          onClick={(e) => e.target === dialogRef.current && setOpen(false)}
          className="fixed inset-x-0 top-auto bottom-0 m-0 max-h-[85vh] w-full max-w-none overflow-y-auto rounded-t-2xl border-t border-border bg-white p-0 text-ink backdrop:bg-ink/40 sm:inset-y-0 sm:right-0 sm:left-auto sm:h-full sm:max-h-none sm:w-[min(26rem,92vw)] sm:rounded-t-none sm:rounded-l-2xl sm:border-t-0 sm:border-l"
        >
          <div className="min-h-full p-5 pb-8 sm:p-6">
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
        </dialog>
      )}
    </>
  );
}
