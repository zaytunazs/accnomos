import Link from "next/link";
import FileTree from "@/components/files/FileTree";

export default function FilesPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">Files</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            A live view of your Accnomos folder in OneDrive. You can open
            everything without the app.
          </p>
        </div>
        <Link
          href="#"
          className="shrink-0 rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
        >
          Open in OneDrive
        </Link>
      </div>
      <FileTree />
    </div>
  );
}
