import { expect, it } from "vitest";
import { confidenceOf, headlineOf, realFormulas } from "./Notes.jsx";

const cell = { kind: "data", page: 1, evidence_key: "ev-1", value: "3722", raw_text: "3,722", label: "Lợi nhuận · 2024", bbox: [0.1, 0.1, 0.2, 0.12], data_status: "valid" };

it("treats a calculation that only copies one cell as a lookup", () => {
  const answer = { answer: "Lợi nhuận là 3.722 tỷ.", evidence: [cell], formulas: [{ expression: "result = value('ev-1')", result: "3722", inputs: [{ evidence_key: "ev-1", value: "3722", page: 1, bbox: cell.bbox }] }] };
  expect(realFormulas(answer)).toHaveLength(0);
  expect(confidenceOf(answer).text).toBe("Đọc thẳng từ bảng trong báo cáo.");
  expect(headlineOf(answer)).toMatchObject({ value: "3.722", chip: { key: "ev-1", raw: "3,722" } });
});

it("shows a calculated result as the headline, with its inputs as parts", () => {
  const other = { ...cell, evidence_key: "ev-2", value: "2514", raw_text: "2,514" };
  const answer = { answer: "Tăng 1.208.", evidence: [cell, other], formulas: [{ expression: "result = value('ev-1') - value('ev-2')", result: "1208", inputs: [{ evidence_key: "ev-1", value: "3722", page: 1, bbox: cell.bbox, label: "2024" }, { evidence_key: "ev-2", value: "2514", page: 1, bbox: cell.bbox, label: "2023" }] }] };
  const headline = headlineOf(answer);
  expect(headline.value).toBe("1.208");
  expect(headline.chip.parts).toHaveLength(2);
});

it("has no headline when the answer rests on several cells without one result", () => {
  const other = { ...cell, evidence_key: "ev-2" };
  expect(headlineOf({ answer: "", evidence: [cell, other], formulas: [] })).toBeNull();
  expect(headlineOf({ answer: "", not_found: true, evidence: [cell], formulas: [] })).toBeNull();
});

it("adds % to the headline when the sentence writes the result as a percentage at another rounding", () => {
  const other = { ...cell, evidence_key: "ev-2", value: "49880", raw_text: "49.880" };
  const formula = (result) => ({ expression: "result = value('ev-1') / value('ev-2') * 100", result, inputs: [{ evidence_key: "ev-1", value: "3722", page: 1, bbox: cell.bbox }, { evidence_key: "ev-2", value: "49880", page: 1, bbox: cell.bbox }] });
  expect(headlineOf({ answer: "Chiếm 42,80% tổng.", evidence: [cell, other], formulas: [formula("42.8")] }).value).toBe("42,8%");
  expect(headlineOf({ answer: "Chiếm 7,46 % tổng.", evidence: [cell, other], formulas: [formula("7.4619")] }).value).toMatch(/%$/);
  expect(headlineOf({ answer: "Tăng 42,8 tỷ.", evidence: [cell, other], formulas: [formula("42.8")] }).value).not.toMatch(/%$/);
});
