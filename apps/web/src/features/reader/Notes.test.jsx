import { expect, it } from "vitest";
import { confidenceOf, headlineOf, realFormulas } from "./Notes.jsx";

const cell = { kind: "data", page: 1, evidence_key: "ev-1", value: "3722", raw_text: "3,722", label: "Lợi nhuận · 2024", bbox: [0.1, 0.1, 0.2, 0.12], data_status: "valid" };

it("treats a calculation that only copies one cell as a lookup", () => {
  const answer = { answer: "Lợi nhuận là 3.722 tỷ.", evidence: [cell], formulas: [{ expression: "result = value('ev-1')", result: "3722", inputs: [{ evidence_key: "ev-1", value: "3722", page: 1, bbox: cell.bbox }] }] };
  expect(realFormulas(answer)).toHaveLength(0);
  expect(confidenceOf(answer)).toBeNull();
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
  // Not "sum_q1": the name comes from the formula's shape (a + c).
  expect(headline.label).toBe("Tổng");
});

it("picks the closest result the sentence writes as a percentage", async () => {
  const { headlineOf } = await import("./Notes.jsx");
  const inputs = [{ evidence_key: "a", value: "3", page: 1, bbox: cell.bbox }, { evidence_key: "b", value: "94", page: 1, bbox: cell.bbox }];
  const formula = { expression: "a = value('a')\nb = value('b')\nresult = {'count': a, 'share': round(a / b * 100, 1)}", result: "{}", inputs,
    result_rows: [{ name: "count", value: "3", source_keys: ["a"] }, { name: "share", value: "3.2", source_keys: ["a", "b"] }] };
  expect(headlineOf({ answer: "Có 3 chi nhánh, chiếm 3% tổng.", evidence: [], formulas: [formula] })).toMatchObject({ result: "share" });
});

it("adds no line for numbers read straight from the report, and flags the ones that need a look", () => {
  const prose = { ...cell, method_label: "đọc từ văn bản" };
  expect(confidenceOf({ answer: "Mục tiêu là 250 tỷ đồng.", evidence: [prose] })).toBeNull();
  expect(confidenceOf({ answer: "…", evidence: [prose, { ...cell, evidence_key: "ev-2", method_label: "đọc từ ô bảng" }] })).toBeNull();
  expect(confidenceOf({ answer: "…", evidence: [{ ...cell, method_label: "đọc bằng OCR" }] }).text).toBe("1 số đọc từ ảnh, có thể sai");
  expect(confidenceOf({ answer: "…", evidence: [{ kind: "text", page: 3, quote: "Mục tiêu tăng trưởng" }] }).text).toBe("Xem trang 3");
});

it("offers the choices of a clarifying question", async () => {
  const { clarifyOptions } = await import("./Notes.jsx");
  expect(clarifyOptions({ options: ["Số tuyệt đối", "Phần trăm"] })).toEqual(["Số tuyệt đối", "Phần trăm"]);
  expect(clarifyOptions({ presentation: "clarification_v1", sections: [{ points: ["Quý 1", "Quý 2"] }] })).toEqual(["Quý 1", "Quý 2"]);
  expect(clarifyOptions({ answer: "Tổng là 30." })).toEqual([]);
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

it("says a number comes from a chart, and that an axis estimate may be wrong", () => {
  const bar = { ...cell, page: 2, evidence_key: "chart-1", value: "38", method_label: "đọc từ nhãn" };
  expect(confidenceOf({ answer: "Tháng 1 đạt 38.", evidence: [bar], formulas: [] })).toEqual({ kind: "neutral", text: "Số đọc từ nhãn trên biểu đồ, trang 2" });
  const estimate = { ...bar, evidence_key: "chart-2", method_label: "ước lượng theo trục", data_status: "ambiguous" };
  expect(confidenceOf({ answer: "…", evidence: [bar, estimate], formulas: [] }).text).toBe("1 số ước lượng từ biểu đồ, có thể sai");
  // A table answer still has no line.
  expect(confidenceOf({ answer: "…", evidence: [{ ...cell, method_label: "đọc từ ô bảng" }], formulas: [] })).toBeNull();
});

it("names a result the script does not name from its formula: a − b is a difference", async () => {
  const { headlineOf, formulaName } = await import("./Notes.jsx");
  const inputs = [{ evidence_key: "q2", value: "49880", page: 1, bbox: cell.bbox }, { evidence_key: "q1", value: "42290", page: 1, bbox: cell.bbox }];
  const formula = { expression: "q2 = value('q2')\nq1 = value('q1')\nresult = q2 - q1", result: "7590", inputs };
  expect(headlineOf({ answer: "Tăng 7.590 triệu đồng.", evidence: [], formulas: [formula] }).label).toBe("Chênh lệch");
  expect(formulaName({ expression: "result = (value('a') - value('b')) / value('b') * 100" })).toBe("Tỷ lệ thay đổi");
  expect(formulaName({ expression: "result = value('a') * 2 - value('b')" })).toBe("");
});

it("gives each failure plain words: the server's own text when it names the cause, else the client's", async () => {
  const { friendlyError, answerError, briefError } = await import("./Notes.jsx");
  const busy = "Hệ thống đang bận. Thử lại sau một phút.";
  // As the worker writes a rate-limited answer: its message and structured_answer.error_code.
  const limited = "Trợ lý đang quá tải. Thử lại sau một phút.";
  expect(friendlyError(answerError({ status: "failed", body: limited, structured_answer: { presentation: "error_v1", answer: limited, error_code: "AI_RATE_LIMITED" } }))).toBe(limited);
  // Older failed answers carry only the generic text: a busy code still says when to retry.
  expect(friendlyError(answerError({ status: "failed", body: "Không thể tạo câu trả lời. Hãy thử lại.", error_code: "AI_BUSY" }))).toBe(busy);
  expect(friendlyError(answerError({ status: "failed", body: "Không thể tạo câu trả lời. Hãy thử lại.", structured_answer: { warnings: ["JOB_FAILED", "RATE_LIMITED"] } }))).toBe(busy);
  expect(friendlyError(answerError({ status: "failed", body: "Không thể tạo câu trả lời. Hãy thử lại." }))).toBe("Không trả lời được. Thử lại.");
  expect(friendlyError({ message: "Rate limit hit (HTTP 429)" })).toBe(busy);
  // A server error that reached the client as a failed fetch is not "check your network".
  expect(friendlyError({ message: "Không kết nối được. Thử lại.", code: "SERVER_ERROR" })).toBe("Máy chủ gặp lỗi. Thử lại.");
  expect(friendlyError({ message: "Không kết nối được. Thử lại." })).toMatch(/Kiểm tra mạng/);
  // Vietnamese words with "ai" in them are not the AI.
  expect(friendlyError({ message: "Số này sai rồi" })).toBe("Số này sai rồi");
  // The overview: the server's words for its own failures, a reason for a busy or slow service, else a plain line.
  expect(briefError({ message: "Tóm tắt mất quá lâu. Thử lại sau.", code: "BRIEF_TIMEOUT", status: 504 })).toBe("Tóm tắt mất quá lâu. Thử lại sau.");
  expect(briefError({ message: "Chưa tóm tắt được báo cáo này. Thử lại sau.", code: "BRIEF_INCOMPLETE", status: 502 })).toBe("Chưa tóm tắt được báo cáo này. Thử lại sau.");
  expect(briefError({ message: limited, code: "AI_RATE_LIMITED", status: 502 })).toBe(`Chưa tóm tắt được. ${limited}`);
  expect(briefError({ message: "Không nhận được phản hồi. Thử lại." })).toBe("Chưa tóm tắt được. Tóm tắt lâu quá nên đã dừng.");
  expect(briefError({ message: "Không trả lời được. Thử lại.", code: "AI_INVALID_OUTPUT", status: 502 })).toBe("Chưa tóm tắt được");
});

it("knows when an answer's numbers changed, were put back, or were corrected before it was made", async () => {
  const { inputState } = await import("./Notes.jsx");
  const answer = { evidence: [{ ...cell, evidence_key: "q1", value: "42290" }], formulas: [{ inputs: [{ evidence_key: "q1", value: "42290" }, { evidence_key: "q2", value: "49880" }] }] };
  const now = (q1, original = "42290") => [{ evidence_key: "q1", current_numeric_value: q1, original_numeric_value: original }, { evidence_key: "q2", current_numeric_value: "49880", original_numeric_value: "49880" }];
  expect(inputState(answer, now("42380")).changed).toBe(true);
  expect(inputState(answer, now("42290")).changed).toBe(false);
  expect(inputState(answer, []).changed).toBeNull();
  // Made after 220 was corrected to 250: it uses the corrected number, and the PDF prints the old one.
  const made = { evidence: [{ ...cell, evidence_key: "goal", value: "250" }] };
  expect(inputState(made, [{ evidence_key: "goal", current_numeric_value: "250", original_numeric_value: "220" }]).edited).toEqual([{ key: "goal", value: "250", printed: "220" }]);
});

it("after a swap, lists the chosen cell in the sources and runs the swapped calculation", async () => {
  const { swappedAnswer } = await import("./Notes.jsx");
  const answer = { evidence: [{ ...cell, evidence_key: "total", value: "42290" }, { ...cell, evidence_key: "q2", value: "49880" }, { kind: "text", page: 1, quote: "Tổng 42.290 49.880" }], formulas: [{ expression: "old" }] };
  const swap = { formulaIndex: 0, swap: { total: "north" }, formula: { expression: "new", inputs: [{ evidence_key: "north", value: "18240", page: 1, bbox: cell.bbox, label: "Miền Bắc" }, { evidence_key: "q2", value: "49880", page: 1 }] } };
  const shown = swappedAnswer(answer, swap);
  expect(shown.evidence.filter((item) => item.kind === "data").map((item) => [item.evidence_key, item.value])).toEqual([["north", "18240"], ["q2", "49880"]]);
  expect(shown.formulas[0].expression).toBe("new");
  expect(answer.formulas[0].expression).toBe("old");
});

it("copies the answer with the pages it comes from", async () => {
  const { copyableAnswer } = await import("./Notes.jsx");
  expect(copyableAnswer("Tăng **7.590** triệu đồng.", [1, 2])).toBe("Tăng 7.590 triệu đồng.\nNguồn: trang 1, 2");
});
