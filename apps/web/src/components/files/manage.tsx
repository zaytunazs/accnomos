/** Shared look and helpers for the Files page's storage, search, archive and backup panels. */

export const card = "flex min-w-0 flex-col gap-3 rounded-2xl border border-border bg-white p-4 sm:p-5";
export const primary =
  "min-h-11 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark disabled:bg-border disabled:text-muted";
export const secondary =
  "min-h-11 whitespace-nowrap rounded-xl border-2 border-teal bg-white px-4 py-2 text-sm font-bold text-teal-dark disabled:border-border disabled:text-muted";
export const field = "min-h-11 w-full min-w-0 rounded-xl border border-border bg-white px-3 py-2 text-sm";
export const label = "flex min-w-0 flex-col gap-1 text-[13px] font-bold text-muted";

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024).toLocaleString("en-GB")} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toLocaleString("en-GB", { maximumFractionDigits: 1 })} MB`;
  return `${(n / 1024 / 1024 / 1024).toLocaleString("en-GB", { maximumFractionDigits: 2 })} GB`;
}

export const pounds = (pence: number) =>
  `£${(pence / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const day = (iso: string) => {
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

export const count = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;

/** The runtime's message without the "(status 400)" tail. */
export const reason = (e: unknown) => ((e as Error).message ?? String(e)).replace(/ \(status \d+[^)]*\)$/, "");

export function ShowInOneDrive({ url, name }: { url: string | null; name: string }) {
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      aria-label={`Show in OneDrive: ${name}`}
      className="inline-flex min-h-11 shrink-0 items-center whitespace-nowrap text-[13px] font-bold text-teal-dark hover:underline"
    >
      Show in OneDrive
    </a>
  );
}
