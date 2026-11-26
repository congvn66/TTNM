import { expect, it } from "vitest";
import { dataStatusLabel, differsFromReading, distinctFormulas, formatNumber, needsCheck, numbersDiffer, readableLabel, resultRows, scriptResultRows, withoutDecimalRepr } from "./format.js";

it("formats canonical decimals in Vietnamese style", () => {
  expect(formatNumber("21350")).toBe("21.350");
  expect(formatNumber("17.05")).toBe("17,05");
  expect(formatNumber("-1234567.5")).toBe("-1.234.567,5");
  expect(formatNumber("21.350 tỷ")).toBe("21.350 tỷ");
  expect(formatNumber("5400.20")).toBe("5.400,2");
  expect(formatNumber("41.90")).toBe("41,9");
  expect(formatNumber("1120.00")).toBe("1.120");
  expect(formatNumber("42.03")).toBe("42,03");
});

it("compares numbers, not spellings", () => {
  expect(numbersDiffer("1300", "1300.0")).toBe(false);
  expect(numbersDiffer("21350", "21500")).toBe(true);
  expect(numbersDiffer(null, "1")).toBe(false);
});

it("removes internal keys and codes from labels", () => {
  expect(readableLabel("ev-text-95991c710a8f7f4e")).toBe("");
  expect(readableLabel("doanh_thu · 2026")).toBe("Doanh thu · 2026");
  expect(readableLabel("Tổng / - · Lợi nhuận gộp")).toBe("Tổng · Lợi nhuận gộp");
  expect(readableLabel("Miền Bắc · Doanh thu thuần / Quý 1/2026")).toBe("Miền Bắc · Doanh thu thuần / Quý 1/2026");
});

it("turns a script result into readable rows", () => {
  expect(resultRows('{"diff": "2114", "percent": "49.66"}')).toEqual([{ name: "diff", value: "2.114" }, { name: "percent", value: "49,66" }]);
  expect(resultRows("92170")).toEqual([{ name: "", value: "92.170" }]);
  expect(resultRows('["1", "2.5"]')).toEqual([{ name: "1", value: "1" }, { name: "2", value: "2,5" }]);
});

it("never shows a Python literal or a Decimal", () => {
  expect(resultRows("{'bac_diff': Decimal('3110'), 'nam': {'q1': Decimal('-12.5')}}")).toEqual([{ name: "Bac diff", value: "3.110" }, { name: "nam · q1", value: "-12,5" }]);
  expect(resultRows('{"a": {"b": ["1", "2"]}}')).toEqual([{ name: "a · b · 1", value: "1" }, { name: "a · b · 2", value: "2" }]);
  expect(resultRows("Decimal('92170')")).toEqual([{ name: "", value: "92.170" }]);
  expect(withoutDecimalRepr("tong = Decimal('39590')")).toBe("tong = 39590");
});

it("labels script result rows with the API's label, else the script's name", () => {
  expect(scriptResultRows({ result: "{}", result_rows: [
    { label: "Chênh lệch Miền Bắc", name: "bac_diff", value: "3110", source_keys: ["ev-1", "ev-2"] },
    { label: "Miền Bắc · Quý 2/2026", name: "dt_bac_q2", value: "21350", source_keys: ["ev-1"] },
    { label: "tong_ca_nam", name: "tong_ca_nam", value: "39590", source_keys: ["ev-1", "ev-2"] },
    { name: "total", value: "1", source_keys: [] },
  ] })).toEqual([
    { name: "Chênh lệch Miền Bắc", value: "3.110" },
    { name: "Miền Bắc · Quý 2/2026", value: "21.350" },
    { name: "Tong ca nam", value: "39.590" },
    { name: "total", value: "1" },
  ]);
  expect(scriptResultRows({ result: '{"x": "1"}' })).toEqual([{ name: "x", value: "1" }]);
});

it("shows a calculation that was run twice once", () => {
  const run = { expression: "result = value('ev-1')", result: "21350" };
  expect(distinctFormulas([run, { ...run }, { ...run, result: "1" }])).toHaveLength(2);
});

it("says a no-data cell has no data, and asks to check only unverified numbers", () => {
  expect(dataStatusLabel("missing")).toBe("Không có số liệu");
  expect(dataStatusLabel("unreadable")).toBe("Chưa đọc được số");
  expect(dataStatusLabel("ambiguous")).toBe("Chưa rõ là số nào");
  expect(dataStatusLabel("valid")).toBe("");
  expect(needsCheck("missing")).toBe(false);
  expect(needsCheck("valid")).toBe(false);
  expect(needsCheck("ambiguous")).toBe(true);
  expect(needsCheck("error")).toBe(true);
});

it("counts a value given to a number the reading could not get as an edit", () => {
  expect(differsFromReading("18240", null)).toBe(true);
  expect(differsFromReading("18240", "18240.0")).toBe(false);
  expect(differsFromReading("18250", "18240")).toBe(true);
  expect(differsFromReading(null, null)).toBe(false);
});
