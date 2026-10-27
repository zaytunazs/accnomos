/**
 * Browser CSV exports, built from data already on the page (no new runtime
 * routes). Money is passed through exactly as the runtime gave it — pence
 * stay pence — so the file always agrees with the screen.
 */

export const SAMPLE_LABEL = "SAMPLE — FICTIONAL COMPANY";

export type CsvValue = string | number | null | undefined;

/**
 * One RFC 4180 cell: quoted (with doubled quotes) when it holds a comma,
 * quote or line break. Cells starting with `=`, `+`, `-` or `@` get a
 * leading apostrophe so Excel never runs them as a formula.
 */
export function csvCell(value: CsvValue): string {
  let s = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Rows joined with CRLF, as RFC 4180 asks. No BOM, no sample line. */
export function csvRows(rows: CsvValue[][]): string {
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

/**
 * The whole file: a UTF-8 BOM so Excel opens it cleanly, the
 * `SAMPLE — FICTIONAL COMPANY` first line when the page shows sample data
 * (signed out), then the records with a trailing CRLF.
 */
export function csvText(rows: CsvValue[][], opts?: { sample?: boolean }): string {
  return `\uFEFF${opts?.sample ? `${SAMPLE_LABEL}\r\n` : ""}${csvRows(rows)}\r\n`;
}

/** `accnomos-<page>-<yyyy-mm-dd>.csv` in UK English (local date). */
export function csvFilename(page: string, at: Date = new Date()): string {
  const day = String(at.getDate()).padStart(2, "0");
  const month = String(at.getMonth() + 1).padStart(2, "0");
  return `accnomos-${page}-${at.getFullYear()}-${month}-${day}.csv`;
}

/** Save the rows as a `.csv` download in the browser. */
export function downloadCsv(filename: string, rows: CsvValue[][], opts?: { sample?: boolean }): void {
  const url = URL.createObjectURL(new Blob([csvText(rows, opts)], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
