import ExplainMore from "@/components/ExplainMore";
import LiveFiles from "@/components/files/LiveFiles";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "Files · Accnomos" };

export default function FilesPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Files"
        description="A live view of your Accnomos folder in OneDrive. You can open everything without the app."
        action={
          <ExplainMore title="What the Files page shows" anchor="files">
            This is your OneDrive folder shown as is, no AI. Books.xlsx is a read-only copy rebuilt from the events; a folder’s file count can include nested folders.
          </ExplainMore>
        }
      />
      <LiveFiles />
    </div>
  );
}
