import { filesTree } from "@/lib/sample-files";

function FolderIcon() {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      className="shrink-0 text-teal"
    >
      <path
        d="M1.5 4.5a1 1 0 0 1 1-1h4l1.5 2h6.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-12a1 1 0 0 1-1-1v-8Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      className="shrink-0 text-muted"
    >
      <path
        d="M4 1.5h5.5L13 5v11.5H4V1.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M9.5 1.5V5H13"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function FileTree() {
  return (
    <ul className="flex flex-col overflow-hidden rounded-2xl border border-border bg-white">
      {filesTree.map((entry) => (
        <li
          key={entry.name}
          className="flex min-h-[44px] items-center gap-3 border-b border-border px-4 py-2.5 last:border-b-0"
        >
          {entry.kind === "folder" ? <FolderIcon /> : <FileIcon />}
          <span className="min-w-0 flex-1 truncate text-[15px] font-semibold">
            {entry.name}
            {entry.kind === "folder" && entry.note ? (
              <span className="ml-2 truncate text-[13px] font-medium text-muted">
                {entry.note}
              </span>
            ) : null}
            {entry.kind === "file" && entry.note ? (
              <span className="ml-2 text-[13px] font-medium text-muted">
                {entry.note}
              </span>
            ) : null}
          </span>
          {entry.kind === "folder" && entry.badgeWarn ? (
            <span className="rounded-full border border-warn-border bg-warn-bg px-2.5 py-0.5 text-[13px] font-bold text-warn-ink">
              {entry.count}
            </span>
          ) : (
            <span className="text-sm font-semibold tabular-nums text-muted">
              {entry.kind === "folder" ? entry.count : ""}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
