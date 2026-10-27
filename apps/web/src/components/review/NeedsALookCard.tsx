export default function NeedsALookCard() {
  return (
    <section
      aria-labelledby="needs-a-look"
      className="rounded-2xl border border-warn-border bg-warn-bg p-5 sm:p-6"
    >
      <span className="inline-block rounded-full border border-warn-border bg-white px-3 py-1 text-[13px] font-bold text-warn-ink">
        Needs a look
      </span>
      <h2
        id="needs-a-look"
        className="mt-2 text-xl font-extrabold tracking-tight text-warn-ink"
      >
        Travis Perkins · £212.40
      </h2>
      <p className="mt-2 text-[15px] leading-7 text-warn-ink">
        Looks like a duplicate of a receipt you approved on 14 Oct (same
        supplier, same total, same invoice number TP-88213). Nothing has been
        posted.
      </p>
      <p className="mt-2 text-[15px] font-bold leading-7 text-warn-ink">
        Suggested fix: keep the 14 Oct entry and archive this file.
      </p>
      <div className="mt-5 flex flex-col gap-3 sm:flex-row">
        <button
          type="button"
          className="h-11 whitespace-nowrap rounded-xl bg-warn-ink px-6 text-[15px] font-bold text-white hover:bg-amber"
        >
          Archive as duplicate
        </button>
        <button
          type="button"
          className="h-11 whitespace-nowrap rounded-xl border border-warn-border bg-white px-6 text-[15px] font-bold text-warn-ink hover:bg-warn-bg"
        >
          It’s different — compare
        </button>
      </div>
    </section>
  );
}
