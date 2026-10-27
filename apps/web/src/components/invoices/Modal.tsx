"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** Dialog in the SubmitSheet style: backdrop button, Escape closes, focus moves to the heading. */
export default function Modal({
  id, title, onClose, children, wide = false,
}: { id: string; title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    // Once per opening: a parent re-rendering with a new onClose must not pull focus out of a field.
    headingRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeRef.current();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <button type="button" aria-label="Close" onClick={onClose} className="absolute inset-0 cursor-default bg-ink/50" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        className={`relative max-h-[92vh] w-full overflow-y-auto rounded-2xl border border-border bg-white p-5 sm:p-6 ${wide ? "max-w-3xl" : "max-w-lg"}`}
      >
        <h2 id={id} ref={headingRef} tabIndex={-1} className="text-xl font-extrabold tracking-tight outline-none">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

export const fieldLabel = "text-xs font-bold text-muted";
export const fieldInput = "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
export const fieldArea = "mt-1 w-full rounded-xl border border-border bg-white px-3 py-2 text-[15px] leading-6 text-ink";
export const primaryButton = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
export const secondaryButton = "h-11 rounded-xl border border-border bg-white px-5 text-[15px] font-bold text-ink hover:bg-ground disabled:opacity-60";
