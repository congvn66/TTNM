import { expect, it } from "vitest";
import { formatNumber, numbersDiffer, readableLabel, resultRows } from "./format.js";

it("formats canonical decimals in Vietnamese style", () => {
  expect(formatNumber("21350")).toBe("21.350");
  expect(formatNumber("17.05")).toBe("17,05");
  expect(formatNumber("-1234567.5")).toBe("-1.234.567,5");
  expect(formatNumber("21.350 tỷ")).toBe("21.350 tỷ");
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
