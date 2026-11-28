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

it("takes the result the sentence states as the headline when a script gives several", async () => {
  const { headlineOf, swappedHeadline } = await import("./Notes.jsx");
  const other = { ...cell, evidence_key: "ev-2", value: "49880", raw_text: "49.880" };
  const inputs = [{ evidence_key: "ev-1", value: "42290", page: 1, bbox: cell.bbox }, { evidence_key: "ev-2", value: "49880", page: 1, bbox: cell.bbox }];
  const formula = { expression: "q1 = value('ev-1')\nq2 = value('ev-2')\ndiff = q2 - q1\npct = round((diff / q1) * 100, 2)\nresult = {\"diff\": diff, \"pct\": pct}", result: "{\"diff\": \"7590\", \"pct\": \"17.95\"}",
    result_rows: [{ name: "diff", value: "7590", source_keys: ["ev-1", "ev-2"] }, { name: "pct", value: "17.95", source_keys: ["ev-1", "ev-2"] }], inputs };
  const headline = headlineOf({ answer: "Tăng 7.590 triệu đồng (tương đương 17,95%).", evidence: [cell, other], formulas: [formula] });
  expect(headline).toMatchObject({ value: "17,95%", result: "pct" });
  expect(headline.chip.parts.map((part) => part.index)).toEqual([0, 1]);

  // The same result of the script run on another cell keeps its % and remembers the original.
  const swapped = swappedHeadline(headline, { ...formula, result_rows: [{ name: "diff", value: "1000" }, { name: "pct", value: "2.5" }], inputs });
  expect(swapped).toMatchObject({ value: "2,5%", original: "17,95%" });
});

it("shows only the cells behind the stated result, keeping their numbers, and never a script's variable name", async () => {
  const { headlineOf } = await import("./Notes.jsx");
  const input = (key, value) => ({ evidence_key: key, value, page: 1, bbox: cell.bbox });
  const formula = { expression: "a = value('a')\nb = value('b')\nc = value('c')\nresult = {'sum_q1': a + c, 'other': b}", result: "{}",
    result_rows: [{ name: "sum_q1", value: "24050", source_keys: ["a", "c"] }, { name: "other", value: "9860", source_keys: ["b"] }],
    inputs: [input("a", "8120"), input("b", "9860"), input("c", "15930")] };
  const headline = headlineOf({ answer: "Tổng là 24.050.", evidence: [], formulas: [formula] });
  expect(headline.inputs.map((item) => [item.evidence_key, item.index])).toEqual([["a", 0], ["c", 2]]);
  expect(headline.chip.parts.map((part) => part.index)).toEqual([0, 2]);
  expect(headline.chip.boxes).toHaveLength(2);
  expect(headline.label).toBe("");
});

it("picks the closest result the sentence writes as a percentage", async () => {
  const { headlineOf } = await import("./Notes.jsx");
  const inputs = [{ evidence_key: "a", value: "3", page: 1, bbox: cell.bbox }, { evidence_key: "b", value: "94", page: 1, bbox: cell.bbox }];
  const formula = { expression: "a = value('a')\nb = value('b')\nresult = {'count': a, 'share': round(a / b * 100, 1)}", result: "{}", inputs,
    result_rows: [{ name: "count", value: "3", source_keys: ["a"] }, { name: "share", value: "3.2", source_keys: ["a", "b"] }] };
  expect(headlineOf({ answer: "Có 3 chi nhánh, chiếm 3% tổng.", evidence: [], formulas: [formula] })).toMatchObject({ result: "share" });
});

it("says a number read from a paragraph came from the text, not a table", () => {
  const prose = { ...cell, method_label: "đọc từ văn bản" };
  expect(confidenceOf({ answer: "Mục tiêu là 250 tỷ đồng.", evidence: [prose] }).text).toBe("Đọc thẳng từ đoạn văn trong báo cáo.");
  expect(confidenceOf({ answer: "…", evidence: [prose, { ...cell, evidence_key: "ev-2", method_label: "đọc từ ô bảng" }] }).text).toBe("Đọc thẳng từ bảng và đoạn văn trong báo cáo.");
});

it("has no headline when the sentence lists several results of one script", () => {
  const months = [["T2", "35"], ["T3", "41"], ["T4", "44"], ["T5", "49"], ["T6", "47"]];
  const inputs = months.map(([, value], index) => ({ evidence_key: `ev-${index}`, value, page: 2, bbox: cell.bbox }));
  const formula = { expression: months.map(([name], index) => `${name.toLowerCase()} = value('ev-${index}')`).join("\n") + "\nresult = {" + months.map(([name]) => `"${name}": ${name.toLowerCase()}`).join(", ") + "}",
    result: JSON.stringify(Object.fromEntries(months)), result_rows: months.map(([name, value], index) => ({ name, value, source_keys: [`ev-${index}`] })), inputs };
  const answer = { answer: "Tháng 2 là 35 nghìn, tháng 3 là 41 nghìn, tháng 4 là 44 nghìn, tháng 5 là 49 nghìn, tháng 6 là 47 nghìn.", evidence: inputs.map((input) => ({ ...cell, ...input })), formulas: [formula] };
  expect(headlineOf(answer)).toBeNull();
  // The same script stating one month still has that month as its headline.
  expect(headlineOf({ ...answer, answer: "Tháng 4 là 44 nghìn đơn." })?.value).toBe("44");
});

it("names a chart as the source of numbers read from its labels", () => {
  const bar = { ...cell, evidence_key: "chart-1", value: "38", method_label: "đọc từ nhãn", source_type: "chart" };
  expect(confidenceOf({ answer: "Tháng 1 đạt 38.", evidence: [bar], formulas: [] }).text).toBe("Đọc thẳng từ biểu đồ trong báo cáo.");
  expect(confidenceOf({ answer: "", evidence: [bar, { ...cell, method_label: "đọc từ ô bảng" }], formulas: [] }).text).toBe("Đọc thẳng từ bảng và biểu đồ trong báo cáo.");
});
