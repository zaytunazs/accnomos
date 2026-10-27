"use client";

import { useState } from "react";
import Modal from "@/components/review/Modal";
import {
  buildEdits,
  CATEGORIES,
  initialForm,
  validate,
  vatCodeLabel,
  vatCodesOf,
  VERIFIER_FIELD,
  type EditField,
  type EditForm,
} from "@/lib/review-edit";
import type { RtProposal } from "@/lib/runtime";

const shown = (v: string | number | null) => (v === null || v === "" ? "none" : typeof v === "number" ? v.toFixed(2) : v);

/**
 * Correct a proposal, then approve it with the corrections in one step.
 * Save & approve stays disabled, with the reason shown, while anything is invalid.
 */
export default function EditSheet({
  proposal,
  busy,
  onCancel,
  onSave,
}: {
  proposal: RtProposal;
  busy: boolean;
  onCancel: () => void;
  onSave: (edits: Record<string, string | number>) => void;
}) {
  const [form, setForm] = useState<EditForm>(() => initialForm(proposal));
  const problems = validate(proposal, form);
  const edits = buildEdits(proposal, form);
  const codes = vatCodesOf(proposal);
  const v = proposal.verification;
  const id = `edit-${proposal.id}`;

  const problemFor = (f: EditField) => problems.find((p) => p.field === f)?.message;
  /** The second reading of this field when it disagreed with the first, else null. */
  const disagreed = (f: EditField) => {
    const key = VERIFIER_FIELD[f];
    const field = key && v && !v.error ? v.fields[key] : undefined;
    return field && !field.agree ? shown(field.verifier) : null;
  };

  function renderField({ field, label, type = "text", inputMode }: { field: EditField; label: string; type?: string; inputMode?: "decimal" }) {
    const problem = problemFor(field);
    const second = disagreed(field);
    return (
      <div className={`flex flex-col gap-1 rounded-xl ${second ? "border border-warn-border bg-warn-bg p-2" : ""}`}>
        <label htmlFor={`${id}-${field}`} className="text-[13px] font-semibold text-muted">
          {label}
        </label>
        <input
          id={`${id}-${field}`}
          type={type}
          inputMode={inputMode}
          value={form[field]}
          onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.value }))}
          aria-invalid={problem ? true : undefined}
          aria-describedby={[problem && `${id}-${field}-problem`, second && `${id}-${field}-second`].filter(Boolean).join(" ") || undefined}
          className={`h-11 w-full min-w-0 rounded-xl border bg-white px-3 text-[15px] ${problem ? "border-warn-ink" : "border-border"}`}
        />
        {second && (
          <p id={`${id}-${field}-second`} className="text-[13px] text-warn-ink">
            Second reading disagrees: <strong>{second}</strong>
          </p>
        )}
        {problem && (
          <p id={`${id}-${field}-problem`} className="text-[13px] font-semibold text-warn-ink">
            {problem}
          </p>
        )}
      </div>
    );
  }

  const changed = Object.keys(edits).length;
  return (
    <Modal label={`Edit ${proposal.extracted.supplier_name}`} onClose={onCancel}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!problems.length && !busy) onSave(edits);
        }}
        className="flex flex-col gap-4"
      >
        <h2 className="text-lg font-extrabold tracking-tight">Edit before approving</h2>
        {v && !v.error && !v.agree_all && (
          <p className="rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">
            The second reading disagreed on the highlighted fields. Check them against the document.
          </p>
        )}
        {/* Fields are rendered by a plain function (not a component) so inputs keep focus while typing. */}
        {renderField({ field: "supplier", label: "Supplier" })}
        <div className="grid grid-cols-2 gap-3">
          {renderField({ field: "date", label: "Date", type: "date" })}
          {renderField({ field: "vrn", label: "VAT number" })}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {renderField({ field: "net", label: "Net (£)", inputMode: "decimal" })}
          {renderField({ field: "vat", label: "VAT (£)", inputMode: "decimal" })}
          {renderField({ field: "gross", label: "Total (£)", inputMode: "decimal" })}
        </div>
        <p className="text-[13px] text-muted">
          VAT code {codes.length === 1 ? vatCodeLabel(codes[0]) : codes.length ? `${codes.join(", ")} (mixed rates: checked by line, not here)` : "none"}, as read.
        </p>
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-category`} className="text-[13px] font-semibold text-muted">
            Category
          </label>
          <select
            id={`${id}-category`}
            value={form.category}
            onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
            className="h-11 rounded-xl border border-border bg-white px-3 text-[15px]"
          >
            {!CATEGORIES.includes(form.category) && <option value={form.category}>{form.category}</option>}
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <p role="status" className={`text-sm ${problems.length ? "font-semibold text-warn-ink" : "text-muted"}`}>
          {problems.length
            ? `Can't save yet: ${problems[0].message}${problems.length > 1 ? ` (and ${problems.length - 1} more)` : ""}`
            : changed
              ? `${changed} change${changed === 1 ? "" : "s"} will be sent with the approval.`
              : "No changes: this approves it as read."}
        </p>
        <div className="flex flex-nowrap gap-2">
          <button
            type="submit"
            disabled={problems.length > 0 || busy}
            className="h-11 flex-1 whitespace-nowrap rounded-xl bg-teal px-4 text-[15px] font-bold text-white disabled:opacity-50"
          >
            {busy ? "Working…" : "Save & approve"}
          </button>
          <button type="button" onClick={onCancel} className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-4 text-[15px] font-bold">
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
