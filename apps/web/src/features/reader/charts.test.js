import { describe, expect, it } from "vitest";
import { axisNumber, barValue, chartData, chartTakeaway, niceTicks } from "./charts.js";

const ROWS = ["Miền Bắc", "Miền Trung", "Miền Nam", "Tổng"];
// The current period sits on the left, as many Vietnamese statements do.
const COLUMNS = ["Doanh thu · Quý 2/2026", "Doanh thu · Quý 1/2026", "Biên lợi nhuận %"];
const VALUES = [[220, 200, 30], [90, 100, 25], [190, 100, 28], [500, 400, 28]];
const cell = (r, c, extra = {}) => ({
  evidence_key: `ev-${r}-${c}`, page_number: 1, bbox: [0.3 + c * 0.15, 0.5 + r * 0.02, 0.4 + c * 0.15, 0.515 + r * 0.02],
  current_numeric_value: String(VALUES[r][c]), original_numeric_value: String(VALUES[r][c]), data_status: "valid",
  table_locator: { table_region_key: "t0", row_index: r + 1, column_index: c + 1, row_header: ROWS[r], column_header: COLUMNS[c] }, ...extra,
});
const EVIDENCES = ROWS.flatMap((_, r) => COLUMNS.map((__, c) => cell(r, c)));
const keys = (rows, cols) => rows.flatMap((r) => cols.map((c) => `ev-${r}-${c}`));

describe("chartData", () => {
  it("keeps table rows as groups and puts period columns in time order", () => {
    const data = chartData(keys([0, 1, 2], [0, 1]), EVIDENCES);
    expect(data.groups.map((group) => group.label)).toEqual(["Miền Bắc", "Miền Trung", "Miền Nam"]);
    expect(data.series.map((item) => item.label)).toEqual(["Quý 1/2026", "Quý 2/2026"]);
    expect(data.timeOrdered).toBe(true);
    expect(data.title).toBe("Doanh thu");
  });
  it("leaves the total row out when its parts are there too", () => {
    const data = chartData(keys([0, 1, 2, 3], [0]), EVIDENCES);
    expect(data.groups).toHaveLength(3);
    expect(data.notes[0]).toBe("Không vẽ dòng tổng");
  });
  it("turns one row across periods into columns", () => {
    const data = chartData(keys([3], [0, 1]), EVIDENCES);
    expect(data.turned).toBe(true);
    expect(data.groups.map((group) => group.label)).toEqual(["Quý 1/2026", "Quý 2/2026"]);
    expect(chartTakeaway(data)).toBe("Từ Quý 1/2026 đến Quý 2/2026 tăng 25%.");
  });
  it("starts a percentage column hidden next to amounts", () => {
    const data = chartData(keys([0, 1], [0, 2]), EVIDENCES);
    expect(data.hidden).toEqual(["3"]);
  });
  it("gives shares of the total row, and none for a ratio column", () => {
    const data = chartData(keys([0, 1, 2], [0]), EVIDENCES);
    const first = data.groups[0].bars[0];
    expect(barValue(first, "share", data.share)).toBeCloseTo(44);
    expect(chartData(keys([0, 1], [2]), EVIDENCES).share).toBeNull();
  });
  it("needs two numbers from one table", () => {
    expect(chartData(["ev-0-0"], EVIDENCES)).toBeNull();
    expect(chartData(["missing"], EVIDENCES)).toBeNull();
  });
  it("follows corrected numbers and marks unsure ones", () => {
    const edited = EVIDENCES.map((item) => (item.evidence_key === "ev-0-0" ? { ...item, current_numeric_value: "300" } : item.evidence_key === "ev-1-0" ? { ...item, data_status: "ambiguous" } : item));
    const data = chartData(keys([0, 1], [0]), edited);
    expect(data.groups[0].bars[0].value).toBe(300);
    expect(data.groups[1].bars[0].unsure).toBe(true);
  });
});

describe("chartTakeaway", () => {
  it("names the biggest rise and fall between two periods", () => {
    const data = chartData(keys([0, 1, 2], [0, 1]), EVIDENCES);
    expect(chartTakeaway(data)).toBe("Tăng mạnh nhất từ Quý 1/2026 đến Quý 2/2026: Miền Nam (+90%). Giảm mạnh nhất: Miền Trung (−10%).");
  });
  it("names a row that starts at 0 on its own instead of counting it", () => {
    const zero = EVIDENCES.map((item) => (item.evidence_key === "ev-1-1" ? { ...item, current_numeric_value: "0" } : item.evidence_key === "ev-1-0" ? { ...item, current_numeric_value: "95" } : item));
    const data = chartData(keys([0, 1, 2], [0, 1]), zero);
    expect(chartTakeaway(data)).toBe("Miền Trung từ 0 lên 95. 2 dòng còn lại đều tăng từ Quý 1/2026 đến Quý 2/2026, mạnh nhất là Miền Nam (+90%).");
    expect(chartData(keys([3], [0, 1]), EVIDENCES).title).toBe("Tổng · Doanh thu");
  });
  it("names the largest and smallest bar of one column", () => {
    const data = chartData(keys([0, 1, 2], [0]), EVIDENCES);
    expect(chartTakeaway(data)).toBe("Lớn nhất: Miền Bắc, 220. Nhỏ nhất: Miền Trung, 90.");
    expect(chartTakeaway(data, { mode: "share" })).toBe("Miền Bắc chiếm nhiều nhất: 44%.");
  });
});

describe("axis", () => {
  it("uses round steps that include zero", () => {
    expect(niceTicks(90, 220)).toEqual([0, 50, 100, 150, 200, 250]);
    expect(niceTicks(-30, 80)).toEqual([-50, -25, 0, 25, 50, 75, 100]);
  });
  it("writes large numbers in words", () => {
    expect(axisNumber(2500000)).toBe("2.500.000");
    expect(axisNumber(25000000)).toBe("25 triệu");
    expect(axisNumber(1200000000)).toBe("1,2 tỷ");
    expect(axisNumber(40, true)).toBe("40%");
  });
});

describe("broker tables", () => {
  const row = (r, c, header, value, name) => ({ evidence_key: `b-${r}-${c}`, page_number: 2, bbox: [0.4 + c * 0.1, 0.3 + r * 0.02, 0.45 + c * 0.1, 0.31 + r * 0.02], current_numeric_value: String(value), original_numeric_value: String(value), data_status: "valid",
    table_locator: { table_region_key: "b", row_index: r, column_index: c, row_header: name, column_header: header } });
  const cells = [row(1, 1, "Chênh lệch · 2026E", 7, "- EBIT"), row(1, 0, "Chênh lệch · 2025E", 2, "- EBIT"), row(2, 1, "Chênh lệch · 2026E", 16, "LNST"), row(2, 0, "Chênh lệch · 2025E", 7, "LNST")];
  it("reads estimate years as periods and drops the sub-item dash", () => {
    const data = chartData(cells.map((cell) => cell.evidence_key), cells);
    expect(data.timeOrdered).toBe(true);
    expect(data.series.map((item) => item.label)).toEqual(["2025E", "2026E"]);
    expect(data.groups[0].label).toBe("EBIT");
  });
  it("keeps the % sign of a percentage column", () => {
    const yoy = [row(1, 0, "+/-%YoY", 20.7, "TGDĐ"), row(2, 0, "+/-%YoY", -8.4, "Khác")];
    const data = chartData(yoy.map((cell) => cell.evidence_key), yoy);
    expect(data.percent).toBe(true);
    expect(chartTakeaway(data)).toBe("Lớn nhất: TGDĐ, 20,7%. Nhỏ nhất: Khác, -8,4%.");
  });
  it("hides a weight column next to prices, and says when bars are equal", () => {
    const val = [row(1, 0, "Tỷ trọng", 50, "DCF"), row(1, 1, "Giá dự phóng theo tỷ trọng (VND)", 13.8, "DCF"), row(2, 0, "Tỷ trọng", 50, "P/B"), row(2, 1, "Giá dự phóng theo tỷ trọng (VND)", 12.1, "P/B")];
    const data = chartData(val.map((cell) => cell.evidence_key), val);
    expect(data.hidden).toEqual(["0"]);
    expect(chartTakeaway(data, { off: ["1"] })).toBe("Các cột bằng nhau: 50.");
  });
  it("reads a header split by a spaced slash", () => {
    const slash = [row(1, 0, "Lợi nhuận gộp / Quý 1/2026", 4, "Bắc"), row(1, 1, "Lợi nhuận gộp / Quý 2/2026", 5, "Bắc"), row(2, 0, "Lợi nhuận gộp / Quý 1/2026", 3, "Nam"), row(2, 1, "Lợi nhuận gộp / Quý 2/2026", 6, "Nam")];
    const data = chartData(slash.map((cell) => cell.evidence_key), slash);
    expect(data.title).toBe("Lợi nhuận gộp");
    expect(data.series.map((item) => item.label)).toEqual(["Quý 1/2026", "Quý 2/2026"]);
  });
});

describe("audit cases", () => {
  const at = (r, c, header, value, name) => ({ evidence_key: `a-${r}-${c}`, page_number: 1, bbox: [0.4 + c * 0.1, 0.3 + r * 0.02, 0.45 + c * 0.1, 0.31 + r * 0.02], current_numeric_value: value == null ? null : String(value), original_numeric_value: value == null ? null : String(value), data_status: "valid",
    table_locator: { table_region_key: "a", row_index: r, column_index: c, row_header: name, column_header: header } });
  const make = (cells) => chartData(cells.map((cell) => cell.evidence_key), cells);
  it("keeps one row with an amount and a percentage as rows with toggles, not as time columns", () => {
    const data = make([at(1, 0, "Doanh thu", 1200, "A"), at(1, 1, "Biên lợi nhuận %", 12, "A")]);
    expect(data.turned).toBe(false);
    expect(data.hidden).toEqual(["1"]);
  });
  it("does not hide percentages when the amounts have no numbers", () => {
    expect(make([at(1, 0, "Doanh thu", null, "A"), at(2, 0, "Doanh thu", null, "B"), at(1, 1, "Biên %", 12, "A"), at(2, 1, "Biên %", 15, "B")]).hidden).toEqual([]);
  });
  it("moves a percentage column in points", () => {
    const data = make([at(1, 0, "Biên gộp % · 2025", 10, "A"), at(1, 1, "Biên gộp % · 2026", 12, "A")]);
    expect(chartTakeaway(data)).toBe("Từ 2025 đến 2026 tăng 2 điểm %.");
  });
  it("says flat, from zero downwards, and a single row's move", () => {
    expect(chartTakeaway(make([at(1, 0, "X · 2025", 5, "A"), at(1, 1, "X · 2026", 5, "A")]))).toBe("Từ 2025 đến 2026 không đổi.");
    expect(chartTakeaway(make([at(1, 0, "X · 2025", 5, "A"), at(1, 1, "X · 2026", 5, "A"), at(2, 0, "X · 2025", 3, "B"), at(2, 1, "X · 2026", 3, "B")]))).toBe("Cả 2 dòng không đổi từ 2025 đến 2026.");
    expect(chartTakeaway(make([at(1, 0, "X · 2025", 10, "A"), at(1, 1, "X · 2026", 15, "A"), at(2, 0, "X · 2025", 0, "B"), at(2, 1, "X · 2026", -5, "B")]))).toBe("B từ 0 xuống -5. A tăng 50% từ 2025 đến 2026.");
  });
  it("leaves out a cell whose names changed after a re-read", () => {
    const cells = [at(1, 0, "X", 1, "A"), at(2, 0, "X", 2, "B"), at(3, 0, "X", 3, "C")];
    const data = chartData(cells.map((cell) => cell.evidence_key), cells, { "a-1-0": ["A", "X"], "a-2-0": ["Old", "X"], "a-3-0": ["C", "X"] });
    expect(data.groups.map((group) => group.label)).toEqual(["A", "C"]);
    expect(data.notes[0]).toBe("Không vẽ 1 ô đã thay đổi");
  });
  it("compares two negative numbers by size: a cost that grew is not a fall", () => {
    const data = make([at(1, 0, "X · Q3/2024", -330, "Chi phí tài chính"), at(1, 1, "X · Q3/2025", -411, "Chi phí tài chính"), at(2, 0, "X · Q3/2024", 800, "Doanh thu"), at(2, 1, "X · Q3/2025", 900, "Doanh thu"), at(3, 0, "X · Q3/2024", 100, "Khác"), at(3, 1, "X · Q3/2025", 110, "Khác")]);
    expect(chartTakeaway(data)).toBe("Chi phí tài chính: số âm, độ lớn tăng 24,5% (-330 → -411). 2 dòng còn lại đều tăng từ Q3/2024 đến Q3/2025, mạnh nhất là Doanh thu (+12,5%).");
  });
  it("gives no change of a change, and reads a margin row in points", () => {
    expect(chartTakeaway(make([at(1, 0, "Thay đổi với kỳ trước · 2025", 4, "A"), at(1, 1, "Thay đổi với kỳ trước · 2026", 11, "A")]))).toBe("");
    const margin = make([at(1, 0, "Q2/2025", 21.6, "Biên lợi nhuận gộp"), at(1, 1, "Q2/2026", 20.2, "Biên lợi nhuận gộp")]);
    expect(margin.percent).toBe(true);
    expect(chartTakeaway(margin)).toBe("Từ Q2/2025 đến Q2/2026 giảm 1,4 điểm %.");
  });
  it("leaves margin rows out of a chart of amounts", () => {
    const data = make([at(1, 0, "Q2/2026", 34147, "Doanh thu"), at(2, 0, "Q2/2026", 6892, "Lợi nhuận gộp"), at(3, 0, "Q2/2026", 20.2, "Biên lợi nhuận gộp")]);
    expect(data.groups.map((group) => group.label)).toEqual(["Doanh thu", "Lợi nhuận gộp"]);
    expect(data.notes[0]).toBe("Không vẽ dòng tỷ lệ");
  });
  it("does not rank different measures or a total against its part", () => {
    expect(chartTakeaway(make([at(1, 0, "Doanh thu · Q1", 10, "A"), at(1, 1, "Lợi nhuận · Q2", 3, "A"), at(2, 0, "Doanh thu · Q1", 12, "B"), at(2, 1, "Lợi nhuận · Q2", 4, "B")]))).toBe("");
    expect(chartTakeaway(make([at(1, 0, "X", 10, "Xuất khẩu"), at(2, 0, "X", 400, "Tổng")]))).toBe("");
  });
});

describe("broker table quirks", () => {
  const at = (r, c, header, value, name) => ({ evidence_key: `q-${r}-${c}`, page_number: 1, bbox: [0.4 + c * 0.05, 0.3 + r * 0.02, 0.44 + c * 0.05, 0.31 + r * 0.02], current_numeric_value: String(value), original_numeric_value: String(value), data_status: "valid",
    table_locator: { table_region_key: "q", row_index: r, column_index: c, row_header: name, column_header: header } });
  it("skips a footnote column and does not put quarters and nine months in one time order", () => {
    const row = [at(1, 0, "Q3/2024", 8132, "A"), at(1, 1, "Q3/2025", 9535, "A"), at(1, 2, "9M2024", 21649, "A"), at(1, 3, "9M2025", 26130, "A"), at(1, 4, "Chú thích", 7, "A")];
    const data = chartData(row.map((cell) => cell.evidence_key), row);
    expect(data.groups.map((group) => group.label)).toEqual(["Q3/2024", "Q3/2025", "9M2024", "9M2025"]);
    expect(data.timeOrdered).toBe(false);
  });
  it("draws at most five columns, so no colour repeats, and says what it left out", () => {
    const row = ["A", "B", "C", "D", "E", "F"].map((header, c) => at(1, c, header, c + 1, "X")).concat(["A", "B", "C", "D", "E", "F"].map((header, c) => at(2, c, header, c + 2, "Y")));
    const data = chartData(row.map((cell) => cell.evidence_key), row);
    expect(data.series.map((item) => item.label)).toEqual(["A", "B", "C", "D", "E"]);
    expect(data.notes[0]).toBe("Chỉ vẽ 5 cột đầu");
  });
  it("reads 9M2024 as a period and does not rank a quarter against nine months", () => {
    const row = [at(1, 0, "Q3/2024", 8132, "A"), at(1, 1, "Q3/2025", 9535, "A"), at(1, 2, "9M2024", 21649, "A"), at(1, 3, "9M2025", 26130, "A")];
    const data = chartData(row.map((cell) => cell.evidence_key), row);
    expect(chartTakeaway(data)).toBe("");
    const nine = [at(1, 2, "9M2024", 21649, "A"), at(1, 3, "9M2025", 26130, "A")];
    expect(chartTakeaway(chartData(nine.map((cell) => cell.evidence_key), nine))).toBe("Từ 9M2024 đến 9M2025 tăng 20,7%.");
  });
});

