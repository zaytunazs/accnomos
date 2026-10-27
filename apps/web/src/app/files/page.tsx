import LiveFiles from "@/components/files/LiveFiles";

export default function FilesPage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Files</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          A live view of your Accnomos folder in OneDrive. You can open
          everything without the app.
        </p>
      </div>
      <LiveFiles />
    </div>
  );
}
