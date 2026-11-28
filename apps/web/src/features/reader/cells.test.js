import { describe, expect, it } from "vitest";
import { answersUsingCell, cellRange, explainCell, neighbourCell, pageProse, pageTables, selectionQuestions, sentenceAround, summarizeSelection } from "./cells.js";

// Table 1 of the sample report: rows are regions, columns are measure · period.
const ROWS = ["Miền Bắc", "Miền Trung", "Miền Nam", "Xuất khẩu", "Tổng"];
const COLUMNS = ["Doanh thu thuần · Quý 1/2026", "Doanh thu thuần · Quý 2/2026", "Lợi nhuận gộp · Quý 1/2026", "Lợi nhuận gộp · Quý 2/2026"];
const VALUES = [[18240, 21350, 5290, 6405], [8120, 9860, null, 2760], [15930, 17420, 4620, 5050], [0, 1250, 0, 310], [42290, 49880, null, 14625]];
const cell = (r, c, extra = {}) => ({
  evidence_key: `ev-${r}-${c}`, page_number: 1, bbox: [0.2 + c * 0.1, 0.5 + r * 0.02, 0.28 + c * 0.1, 0.515 + r * 0.02],
  current_numeric_value: VALUES[r][c] == null ? null : String(VALUES[r][c]), original_numeric_value: VALUES[r][c] == null ? null : String(VALUES[r][c]), data_status: "valid",
  table_locator: { table_region_key: "page-1-table-0", row_index: r + 2, column_index: c + 1, row_header: ROWS[r], column_header: COLUMNS[c] }, ...extra,
});
const EVIDENCES = ROWS.flatMap((_, r) => COLUMNS.map((__, c) => cell(r, c)));
const table = pageTables(EVIDENCES, 1)[0];

describe("pageTables and keyboard movement", () => {
  it("groups the cells of a page into rows in reading order", () => {
    expect(table.rows).toHaveLength(5);
    expect(table.rows[0].map((item) => item.evidence_key)).toEqual(["ev-0-0", "ev-0-1", "ev-0-2", "ev-0-3"]);
    expect(pageTables(EVIDENCES, 2)).toEqual([]);
  });
  it("moves by arrow keys and stops at the table edge", () => {
    expect(neighbourCell(table, "ev-0-0", 1, 0).evidence_key).toBe("ev-0-1");
    expect(neighbourCell(table, "ev-0-0", 0, 1).evidence_key).toBe("ev-1-0");
    expect(neighbourCell(table, "ev-0-0", -1, 0)).toBeNull();
    expect(neighbourCell(table, "ev-4-3", 0, 1)).toBeNull();
  });
  it("selects the rectangle between two cells", () => {
    expect(cellRange(table, "ev-0-0", "ev-1-1").sort()).toEqual(["ev-0-0", "ev-0-1", "ev-1-0", "ev-1-1"]);
  });
});

describe("explainCell", () => {
  it("compares a region with the other quarter and with the whole table", () => {
    const lines = explainCell(cell(2, 1), EVIDENCES).map((line) => line.text);
    expect(lines[0]).toBe("Quý 1/2026 → Quý 2/2026 tăng 9,35%, thấp hơn cả bảng (17,95%).");
    expect(lines[1]).toBe("Chiếm 34,92% · thứ 2/4");
  });
  it("says a value that starts from zero is new instead of dividing by zero", () => {
    const [first] = explainCell(cell(3, 1), EVIDENCES);
    expect(first).toMatchObject({ unusual: true });
    expect(first.text).toContain("mới phát sinh");
  });
  it("checks a total against the rows above it", () => {
    const [line] = explainCell(cell(4, 3), EVIDENCES);
    expect(line).toMatchObject({ bad: true });
    expect(line.text).toBe("Tổng 4 dòng · lệch 100");
  });
});

describe("selections", () => {
  it("sums a selection and warns about unsure numbers and totals added to their parts", () => {
    const unsure = cell(1, 3, { data_status: "ambiguous" });
    const summary = summarizeSelection([cell(0, 3), unsure, cell(4, 3)]);
    expect(summary).toMatchObject({ count: 3, sum: 6405 + 2760 + 14625 });
    expect(summary.caveats).toEqual(["1 số có thể sai", "gồm dòng tổng, bị cộng trùng"]);
    expect(summarizeSelection([cell(1, 2), cell(0, 2)]).caveats).toEqual(["1 ô trống"]);
  });
  it("writes full questions, and asks for the change instead of a percentage when a value starts at zero", () => {
    const picked = [cell(2, 0), cell(2, 1), cell(3, 0), cell(3, 1)];
    const questions = selectionQuestions(picked, EVIDENCES);
    expect(questions).toContain("Doanh thu thuần của Miền Nam và Xuất khẩu tăng bao nhiêu từ Quý 1/2026 đến Quý 2/2026?");
    expect(questions).toContain("Miền Nam chiếm bao nhiêu phần trăm tổng Doanh thu thuần · Quý 2/2026?");
  });
});

it("finds the answers that use a cell", () => {
  const notes = [
    { id: "n1", question: { body: "Tăng bao nhiêu?" }, reply: { structured_answer: { evidence: [], formulas: [{ inputs: [{ evidence_key: "ev-4-0" }] }] } } },
    { id: "n2", question: { body: "Miền Bắc?" }, reply: { structured_answer: { evidence: [{ evidence_key: "ev-0-0" }] } } },
  ];
  expect(answersUsingCell("ev-4-0", notes)).toEqual([{ id: "n1", question: "Tăng bao nhiêu?" }]);
  expect(answersUsingCell("ev-9-9", notes)).toEqual([]);
});

describe("edge cases from review", () => {
  const one = (key, row, rowIndex, value, extra = {}) => ({ evidence_key: key, page_number: 1, bbox: [0.5, 0.1 + rowIndex * 0.02, 0.6, 0.11 + rowIndex * 0.02], current_numeric_value: value == null ? null : String(value), original_numeric_value: value == null ? null : String(value), raw_text: value == null ? "—" : String(value), data_status: "valid", table_locator: { table_region_key: "s", row_index: rowIndex, column_index: 1, row_header: row, column_header: extra.column ?? "Doanh thu" }, ...extra });

  it("checks each subtotal against its own rows, and ranks a row inside its own group", () => {
    const list = [one("a", "A", 1, 10), one("b", "B", 2, 20), one("ta", "Tổng A", 3, 30), one("c", "C", 4, 5), one("d", "D", 5, 7), one("tb", "Tổng B", 6, 12)];
    expect(explainCell(list[5], list)[0]).toEqual({ text: "Tổng 2 dòng · khớp" });
    expect(explainCell(list[3], list).at(-1).text).toBe("Chiếm 41,67% · thứ 2/2");
  });
  it("agrees with the summary check on rounding, % columns and missing rows", () => {
    const rounded = [one("a", "A", 1, 1.25, { raw_text: "1,25" }), one("b", "B", 2, 2.25, { raw_text: "2,25" }), one("t", "Tổng", 3, 3.49, { raw_text: "3,49" })];
    expect(explainCell(rounded[2], rounded)[0].bad).toBeUndefined();
    const percent = [one("a", "A", 1, 10, { column: "Tỷ lệ %" }), one("b", "B", 2, 20, { column: "Tỷ lệ %" }), one("t", "Tổng", 3, 100, { column: "Tỷ lệ %" })];
    expect(explainCell(percent[2], percent)).toEqual([]);
    const gap = [one("a", "A", 1, 10), one("b", "B", 2, null), one("c", "C", 3, 5), one("t", "Tổng", 4, 40)];
    expect(explainCell(gap[3], gap)).toEqual([]);
  });
  it("gives no share when rows mix gains and losses", () => {
    const list = [one("a", "A", 1, 10), one("b", "B", 2, -20), one("t", "Tổng", 3, -10)];
    expect(explainCell(list[0], list).some((line) => line.text.startsWith("Chiếm"))).toBe(false);
  });
  it("shows a change only between two cells of one row, left to right", () => {
    expect(summarizeSelection([cell(0, 1), cell(0, 0)]).change).toBeCloseTo((21350 - 18240) / 18240 * 100);
    expect(summarizeSelection([cell(0, 0), cell(1, 0)]).change).toBeNull();
  });
  it("warns about double counting only for a total and its own rows", () => {
    const otherTable = { ...cell(0, 3), evidence_key: "x", table_locator: { ...cell(0, 3).table_locator, table_region_key: "page-1-table-9" } };
    expect(summarizeSelection([otherTable, cell(4, 3)]).caveats).toEqual([]);
  });
});

it("keeps a narrow right-aligned dash inside a range of wider numbers", () => {
  const dash = { ...cell(1, 2), bbox: [0.46, 0.52, 0.48, 0.535] };
  const list = EVIDENCES.map((item) => (item.evidence_key === dash.evidence_key ? dash : item));
  const t = pageTables(list, 1)[0];
  expect(cellRange(t, "ev-1-1", "ev-2-2").sort()).toEqual(["ev-1-1", "ev-1-2", "ev-2-1", "ev-2-2"]);
});

it("leaves prose in a notes column out of the tappable grid", () => {
  const note = { ...cell(0, 0), evidence_key: "note", current_numeric_value: null, original_numeric_value: null, raw_text: "Đánh dấu tháng tăng trưởng thứ 2", bbox: [0.7, 0.5, 0.95, 0.56], table_locator: { ...cell(0, 0).table_locator, column_index: 9 } };
  const dash = { ...cell(1, 2), current_numeric_value: null, original_numeric_value: null, raw_text: "—" };
  const keys = pageTables([...EVIDENCES, note].map((item) => (item.evidence_key === dash.evidence_key ? dash : item)), 1)[0].cells.map((item) => item.evidence_key);
  expect(keys).not.toContain("note");
  expect(keys).toContain(dash.evidence_key);
});

describe("swapping an input cell", () => {
  it("warns when a total replaces a row, or another measure replaces this one, and not for a like-for-like swap", async () => {
    const { pickWarning } = await import("./cells.js");
    expect(pickWarning(cell(0, 1), cell(1, 1))).toBe("");
    expect(pickWarning(cell(0, 1), cell(4, 1))).toBe("Ô mới là dòng tổng, ô cũ là dòng chi tiết.");
    expect(pickWarning(cell(0, 1), cell(0, 3))).toContain("Lợi nhuận gộp");
  });
  it("suggests the same row and column, without the cells already used", async () => {
    const { pickCandidates } = await import("./cells.js");
    const keys = pickCandidates(cell(0, 1), EVIDENCES, ["ev-4-1"]).map((item) => item.evidence_key).sort();
    expect(keys).toEqual(["ev-0-0", "ev-0-2", "ev-0-3", "ev-1-1", "ev-2-1", "ev-3-1"]);
  });
});

describe("time order", () => {
  it("reads the period from the header, so a statement with this year on the left still grows forward", async () => {
    const { inTimeOrder, periodRank } = await import("./cells.js");
    expect(periodRank("Quý 2/2026")).toBeGreaterThan(periodRank("Quý 1/2026"));
    expect(periodRank("Q2/25")).toBe(202506);
    expect(periodRank("6 tháng 2026")).toBe(202606);
    expect(periodRank("Năm nay")).toBeGreaterThan(periodRank("Năm trước"));
    const thisYear = { ...cell(0, 0), table_locator: { ...cell(0, 0).table_locator, column_header: "Doanh thu · Năm 2026" } };
    const lastYear = { ...cell(0, 1), table_locator: { ...cell(0, 1).table_locator, column_header: "Doanh thu · Năm 2025" } };
    expect(inTimeOrder(thisYear, lastYear)).toMatchObject({ first: lastYear, from: "Năm 2025", to: "Năm 2026" });
    // 18.240 in 2026 against 21.350 in 2025 is a fall, whatever the column order.
    expect(summarizeSelection([thisYear, lastYear]).change).toBeCloseTo((18240 - 21350) / 21350 * 100);
  });
  it("does not add percentages, and says when a selection mixes measures", () => {
    const pct = (r) => ({ ...cell(r, 0), table_locator: { ...cell(r, 0).table_locator, column_header: "Tỷ lệ % · Quý 1/2026" } });
    expect(summarizeSelection([pct(0), pct(1)])).toMatchObject({ additive: false, caveats: ["cột tỷ lệ, cộng lại không có nghĩa"] });
    expect(summarizeSelection([cell(0, 0), cell(0, 2)]).caveats).toContain("gồm nhiều chỉ tiêu khác nhau");
  });
});

describe("numbers in running text", () => {
  const text = (key, page, bbox, raw, value, extra = {}) => ({ evidence_key: key, source_type: "text", page_number: page, bbox, raw_text: raw, current_numeric_value: value, table_locator: null, ...extra });

  it("lists a page's text numbers in reading order, without table cells or other pages", () => {
    const cells = [
      text("b", 1, [0.6, 0.30, 0.65, 0.32], "31%", "31"),
      text("a", 1, [0.1, 0.30, 0.15, 0.32], "8%", "8"),
      text("c", 1, [0.1, 0.10, 0.15, 0.12], "220", "220"),
      text("other-page", 2, [0.1, 0.1, 0.2, 0.2], "5", "5"),
      { ...text("cell", 1, [0.1, 0.5, 0.2, 0.52], "100", "100"), source_type: "table", table_locator: { table_region_key: "t", row_index: 0, column_index: 0 } },
    ];
    expect(pageProse(cells, 1).map((cell) => cell.evidence_key)).toEqual(["c", "a", "b"]);
  });

  it("cuts the sentence that holds the number out of its paragraph", () => {
    const paragraph = "Chi phí vận chuyển bằng 6,5% doanh thu. Mục tiêu năm 2026 là 220 tỷ đồng. Hết.";
    const start = paragraph.indexOf("220");
    expect(sentenceAround(paragraph, start, start + 3)).toEqual({ before: "Mục tiêu năm 2026 là ", number: "220", after: " tỷ đồng." });
    expect(sentenceAround(paragraph, 0, 999)).toBeNull();
  });

  it("shortens a long sentence at a word on each side", () => {
    const long = `${"rất dài ".repeat(30)}đạt 12 tỷ ${"thêm chữ ".repeat(30)}`;
    const start = long.indexOf("12");
    const part = sentenceAround(long, start, start + 2, 20);
    expect(part.before.startsWith("…")).toBe(true);
    expect(part.after.endsWith("…")).toBe(true);
    expect(part.number).toBe("12");
  });
});

it("warns that a selection of percentage cells cannot be added up", async () => {
  const { summarizeSelection } = await import("./cells.js");
  const cell = (key, raw, value) => ({ evidence_key: key, raw_text: raw, current_numeric_value: value, data_status: "valid", page_number: 1, table_locator: { table_region_key: "t", row_index: Number(key.slice(-1)), column_index: 6, row_header: `Mảng ${key}`, column_header: "Thay đổi" } });
  const summary = summarizeSelection([cell("c1", "+12,1%", "12.1"), cell("c2", "+9,5%", "9.5")]);
  expect(summary.caveats.join(" ")).toMatch(/tỷ lệ/);
});
