export default function VoiceNoteCard() {
  return (
    <section
      aria-labelledby="voice-note"
      className="rounded-2xl border border-border bg-white p-5 sm:p-6"
    >
      <h2
        id="voice-note"
        className="text-xl font-extrabold tracking-tight"
      >
        Parking · £4.00 cash
      </h2>
      <div className="mt-2 flex flex-wrap gap-2">
        <span className="rounded-full bg-teal-tint px-3 py-1 text-[13px] font-bold text-teal-dark">
          Confidence 81%
        </span>
        <span className="rounded-full bg-ground px-3 py-1 text-[13px] font-semibold text-muted">
          Voice note
        </span>
      </div>
      <p className="mt-3 text-[15px] leading-7">
        “Paid four pounds cash for parking at the Croydon job” · 09:14 ·
        Transcribed by Muse Voice · No VAT receipt, so no VAT claimed.
      </p>
      <div className="mt-5 flex flex-col gap-3 sm:flex-row">
        <button
          type="button"
          className="h-11 rounded-xl bg-teal px-6 text-[15px] font-bold text-white hover:bg-teal-dark"
        >
          Approve
        </button>
        <button
          type="button"
          className="h-11 rounded-xl border border-border bg-white px-6 text-[15px] font-bold hover:bg-ground"
        >
          Edit
        </button>
      </div>
    </section>
  );
}
