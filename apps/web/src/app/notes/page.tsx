import LiveNotes from "@/components/notes/LiveNotes";

export const metadata = { title: "Notes · Accnomos", robots: { index: false, follow: false } };

export default function Page() {
  return (
    <div className="flex flex-col gap-5">
      <div className="min-w-0">
        <h1 className="text-3xl font-extrabold tracking-tight">Notes</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Quick notes, typed here or spoken to the assistant (“take a note: call the plumber back”). They are kept in your OneDrive with your books.
        </p>
      </div>
      <LiveNotes />
    </div>
  );
}
