import { describe, expect, it } from "vitest";
import { buildBriefing, checkTableTotals, linkNumbers, readNumberCandidates } from "./reportChecks.js";

const cell = (key, row, rowIndex, column, columnIndex, value, raw) => ({
  evidence_key: key, page_number: 1, bbox: [0.1, 0.1, 0.2, 0.2], raw_text: raw ?? String(value ?? "-"),
  method_label: "đọc từ ô bảng", current_numeric_value: value == null ? null : String(value), data_status: "valid",
  table_locator: { table_region_key: "page-1-table-0", row_index: rowIndex, column_index: columnIndex, row_header: row, column_header: column },
});

describe("readNumberCandidates", () => {
  it("reads Vietnamese and English number styles", () => {
    expect(readNumberCandidates("49.880")).toEqual([49880, 49.88]);
    expect(readNumberCandidates("6,5%")).toEqual([6.5]);
    expect(readNumberCandidates("1,234.5")).toEqual([1234.5]);
    expect(readNumberCandidates("128,4")).toEqual([128.4]);
    expect(readNumberCandidates("abc")).toEqual([]);
  });
});

describe("linkNumbers", () => {
  const answer = { evidence: [{ kind: "data", page: 2, value: "31", raw_text: "31", label: "Miền Trung · Cuối quý 2/2026", evidence_key: "k31", bbox: [0.1, 0.1, 0.2, 0.2] }] };
  it("turns cited numbers into chips and leaves dates alone", () => {
    const parts = linkNumbers("Cuối quý 2/2026, miền Trung có 31 cửa hàng.", answer);
    const chips = parts.filter((part) => part.chip);
    expect(chips).toHaveLength(1);
    expect(chips[0].text).toBe("31");
    expect(chips[0].chip.page).toBe(2);
    expect(parts.map((part) => part.text).join("")).toBe("Cuối quý 2/2026, miền Trung có 31 cửa hàng.");
  });
  it("links a computed result to all its inputs", () => {
    const parts = linkNumbers("Tăng 12,3%", { evidence: [], formulas: [{ result: "12.3%", inputs: [{ page: 1, bbox: [0, 0, 0.1, 0.1], label: "Q1" }, { page: 1, bbox: [0.2, 0, 0.3, 0.1], label: "Q2" }] }] });
    expect(parts.find((part) => part.chip).chip.boxes).toHaveLength(2);
  });
});

describe("checkTableTotals", () => {
  const column = "Doanh thu thuần · Quý 2/2026";
  it("passes a total that matches its rows", () => {
    const checks = checkTableTotals([cell("a", "Bắc", 1, column, 1, 21350, "21.350"), cell("b", "Nam", 2, column, 1, 17420, "17.420"), cell("t", "Tổng", 3, column, 1, 38770, "38.770")]);
    expect(checks).toHaveLength(1);
    expect(checks[0].ok).toBe(true);
  });
  it("flags a total that does not match", () => {
    const [check] = checkTableTotals([cell("a", "Q1", 1, "Doanh thu", 1, 114.3), cell("b", "Q2", 2, "Doanh thu", 1, 128.4), cell("c", "Q3", 3, "Doanh thu", 1, 119.7), cell("d", "Q4", 4, "Doanh thu", 1, 117.8), cell("t", "Tổng cộng", 5, "Doanh thu", 1, 482.0, "482,0")]);
    expect(check.ok).toBe(false);
    expect(check.diff).toBeCloseTo(1.8);
    expect(check.chip.boxes).toHaveLength(5);
  });
  it("skips ratio columns and incomplete rows", () => {
    expect(checkTableTotals([cell("a", "Bắc", 1, "Biên lợi nhuận gộp", 1, 20), cell("b", "Nam", 2, "Biên lợi nhuận gộp", 1, 22), cell("t", "Tổng", 3, "Biên lợi nhuận gộp", 1, 21)])).toHaveLength(0);
    expect(checkTableTotals([cell("a", "Bắc", 1, column, 1, 5), cell("b", "Nam", 2, column, 1, null), cell("t", "Tổng", 3, column, 1, 5)])).toHaveLength(0);
  });
});

describe("buildBriefing", () => {
  it("counts numbers, lists empty cells and writes starter questions", () => {
    const evidences = [
      cell("a", "Bắc", 1, "Doanh thu · Quý 1/2026", 1, 10), cell("b", "Bắc", 1, "Doanh thu · Quý 2/2026", 2, 12),
      cell("c", "Nam", 2, "Doanh thu · Quý 1/2026", 1, null, "-"), cell("d", "Nam", 2, "Doanh thu · Quý 2/2026", 2, 8),
    ];
    const briefing = buildBriefing(evidences);
    expect(briefing.numberCount).toBe(3);
    expect(briefing.tableCount).toBe(1);
    expect(briefing.missing.map((item) => item.label)).toEqual(["Nam · Doanh thu · Quý 1/2026"]);
    expect(briefing.suggestions).toEqual([
      "Doanh thu Quý 1/2026 của Bắc là bao nhiêu?",
      "Doanh thu của Bắc thay đổi bao nhiêu từ Quý 1/2026 đến Quý 2/2026?",
      "Mục nào có doanh thu Quý 2/2026 cao nhất?",
    ]);
  });

  it("writes year questions for tables whose rows are measures", () => {
    const evidences = [cell("a", "Doanh thu thuần (tỷ VND)", 1, "2023", 1, 118280), cell("b", "Doanh thu thuần (tỷ VND)", 1, "2025F", 3, 155535), cell("c", "LNST (tỷ VND)", 2, "2025F", 3, 6900)];
    expect(buildBriefing(evidences).suggestions).toEqual([
      "Doanh thu thuần năm 2025 (dự phóng) là bao nhiêu?",
      "Doanh thu thuần thay đổi bao nhiêu từ năm 2023 đến năm 2025 (dự phóng)?",
      "LNST năm 2025 (dự phóng) là bao nhiêu?",
    ]);
  });

  it("suggests nothing when headers do not read like words", () => {
    const evidences = [cell("a", "Tăng/giảm (%)", 1, "VND 106.100", 1, 5), cell("b", "P/E (x)", 2, "VND 106.100", 1, 6)];
    expect(buildBriefing(evidences).suggestions).toEqual([]);
  });
});
