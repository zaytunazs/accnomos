import { expect, test } from "@playwright/test";
import { penceInWords, quantityInWords, readBack, wholeInWords } from "../src/lib/readback";

// Pure functions: no page. The read-back a spoken card shows so a mis-heard figure is caught before Approve.

test("whole numbers read in British English", () => {
  expect(wholeInWords(0)).toBe("zero");
  expect(wholeInWords(14)).toBe("fourteen");
  expect(wholeInWords(40)).toBe("forty");
  expect(wholeInWords(105)).toBe("one hundred and five");
  expect(wholeInWords(1005)).toBe("one thousand and five");
  expect(wholeInWords(1405)).toBe("one thousand, four hundred and five");
  expect(wholeInWords(2_500_000)).toBe("two million, five hundred thousand");
});

test("money reads as pounds and pence", () => {
  expect(penceInWords(4000)).toBe("forty pounds");
  expect(penceInWords(1400)).toBe("fourteen pounds");
  expect(penceInWords(4050)).toBe("forty pounds and fifty pence");
  expect(penceInWords(100)).toBe("one pound");
  expect(penceInWords(5)).toBe("five pence");
  expect(penceInWords(-250)).toBe("minus two pounds and fifty pence");
});

test("quantities keep their decimals", () => {
  expect(quantityInWords("12.5")).toBe("twelve point five");
  expect(quantityInWords("3.00")).toBe("three");
  expect(quantityInWords("0.25")).toBe("zero point two five");
});

test("each spoken card reads back the figure it acts on", () => {
  expect(readBack("log_mileage", { miles: "14" })).toEqual([{ label: "Distance", figure: "14 miles", words: "fourteen miles" }]);
  expect(readBack("log_timesheet", { hours: "1" })).toEqual([{ label: "Time", figure: "1 hour", words: "one hour" }]);
  expect(readBack("match_bank_line", { amount_pence: 4000 })[0].words).toBe("forty pounds");
  const invoice = readBack("create_invoice", { lines: [{ unit_price_pence: 45000 }], total_pence: 54000 });
  expect(invoice.map((l) => l.label)).toEqual(["Price each", "Total"]);
  expect(invoice[1]).toEqual({ label: "Total", figure: "£540.00", words: "five hundred and forty pounds" });
  expect(readBack("create_invoice", { lines: [{}, {}], total_pence: 100 }).map((l) => l.label)).toEqual(["Total"]);
  expect(readBack("close_month", {})).toEqual([]);
});
