"use client";

import { useEffect, useRef, useState } from "react";
import { csvFilename, downloadCsv } from "@/lib/csv";
import { vatBoxes } from "@/lib/sample-vat";

export default function SubmitSheet() {
  const [open, setOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!open) return;
    headingRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        setConfirmed(false);
        setSubmitted(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open ]);

  function close() {
    setOpen(false);
    setConfirmed(false);
    setSubmitted(false);
  }

  return (
    <>
      <div className="flex flex-col gap-3 sm:flex-row">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="h-11 whitespace-nowrap rounded-xl bg-teal px-6 text-[15px] font-bold text-white hover:bg-teal-dark"
        >
          Submit to HMRC (sandbox)
        </button>
        <button
          type="button"
          onClick={() =>
            downloadCsv(
              csvFilename("vat-return"),
              [["box", "what", "amount"], ...vatBoxes.map((b) => [b.box, b.what, b.amount])],
              { sample: true },
            )
          }
          className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-6 text-[15px] font-bold hover:bg-ground"
        >
          Export calc sheet
        </button>
      </div>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
          <button
            type="button"
            aria-label="Close confirmation"
            onClick={close}
            className="absolute inset-0 cursor-default bg-ink/50"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="submit-sheet-title"
            className="relative w-full max-w-lg rounded-2xl border border-border bg-white p-5 sm:p-6"
          >
            <h2
              id="submit-sheet-title"
              ref={headingRef}
              tabIndex={-1}
              className="text-xl font-extrabold tracking-tight outline-none"
            >
              Confirm VAT return · Q3 2026
            </h2>
            <p className="mt-3 text-[15px] leading-7">
              When you submit this VAT information you are making a legal
              declaration that the information is true and complete. A false
              declaration can result in prosecution.
            </p>
            <label className="mt-4 flex min-h-11 cursor-pointer items-center gap-3 text-[15px] font-semibold">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                className="h-5 w-5 accent-teal"
              />
              I confirm
            </label>
            <div
              aria-live="polite"
              aria-label="Declaration"
              className="mt-3 min-h-6 text-[14px] font-semibold text-teal-dark"
            >
              {submitted ? "Sandbox submission would happen here" : null}
            </div>
            <div className="mt-3 flex flex-col gap-3 sm:flex-row">
              <button
                type="button"
                disabled={!confirmed}
                onClick={() => setSubmitted(true)}
                className="h-11 rounded-xl bg-teal px-6 text-[15px] font-bold text-white hover:bg-teal-dark disabled:cursor-not-allowed disabled:opacity-50"
              >
                Submit
              </button>
              <button
                type="button"
                onClick={close}
                className="h-11 rounded-xl border border-border bg-white px-6 text-[15px] font-bold hover:bg-ground"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
