"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * A native modal <dialog>: focus moves inside, the page behind is inert, Escape closes it,
 * and focus goes back to whatever had it before.
 */
export default function Modal({
  label,
  onClose,
  children,
  wide = false,
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const before = document.activeElement as HTMLElement | null;
    dialog.showModal();
    const cancel = (e: Event) => {
      e.preventDefault(); // we close through React state, so the dialog never ends up closed but mounted
      close.current();
    };
    dialog.addEventListener("cancel", cancel);
    return () => {
      dialog.removeEventListener("cancel", cancel);
      dialog.close();
      before?.focus({ preventScroll: true });
    };
  }, []);

  return (
    <dialog
      ref={ref}
      aria-label={label}
      onClick={(e) => e.target === ref.current && onClose()} // backdrop click
      className={`m-auto max-h-[92dvh] w-[calc(100vw-1.5rem)] overflow-auto rounded-2xl border border-border bg-white p-0 text-ink shadow-xl backdrop:bg-black/50 ${
        wide ? "max-w-5xl" : "max-w-lg"
      }`}
    >
      <div className="p-5 sm:p-6">{children}</div>
    </dialog>
  );
}
