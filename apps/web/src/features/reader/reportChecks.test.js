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

describe("splitColumn", () => {
  it("splits on a spaced slash only before a period word", async () => {
    const { splitColumn } = await import("./reportChecks.js");
    expect(splitColumn("Doanh thu · Quý 1 / 2026")).toEqual({ measure: "Doanh thu", period: "Quý 1 / 2026" });
    expect(splitColumn("Lợi nhuận gộp / Quý 1/2026")).toEqual({ measure: "Lợi nhuận gộp", period: "Quý 1/2026" });
    expect(splitColumn("EV / EBITDA")).toEqual({ measure: "EV / EBITDA", period: "" });
    expect(splitColumn("Chênh lệch · 2026E")).toEqual({ measure: "Chênh lệch", period: "2026E" });
  });
});

describe("total rows", () => {
  it("knows total rows a scan wrote with lost or odd accents", async () => {
    const { isTotalName } = await import("./reportChecks.js");
    for (const name of ["Tổng", "Cộng", "Tổng cộng tài sản", "Téng", "TONG CONG TAI SAN", "“Tổng", "Cong", "Total"]) expect(isTotalName(name)).toBe(true);
    for (const name of ["Công ty mẹ", "Tổng nợ/Vốn chủ (x)", "Doanh thu", "", null]) expect(isTotalName(name)).toBe(false);
  });

  const amounts = (rows, header = "3Q24") => rows.map(([name, value], index) => cell(`r${index}`, name, index + 1, header, 1, value, String(value)));

  it("does not count subtotals twice (broker income table)", () => {
    const rows = [["Thu nhập lãi", 19607], ["Chi phí lãi", -7451], ["Thu nhập lãi thuần", 12156], ["Lãi dịch vụ", 1148], ["Lãi ngoại hối", 96], ["Lãi chứng khoán", 134], ["Góp vốn", 3], ["Thu nhập khác", 1526], ["Thu nhập ngoài lãi", 2907], ["Tổng thu nhập hoạt động", 15063]];
    const [check] = checkTableTotals(amounts(rows));
    expect(check.ok).toBe(true);
    expect(check.count).toBe(2);
  });

  it("checks a grand total over sections and their own rows", () => {
    const rows = [["A. TÀI SẢN NGẮN HẠN", 300], ["I. Tiền", 100], ["Tiền mặt", 60], ["Tiền gửi", 40], ["II. Phải thu", 200], ["Phải thu khách hàng", 150], ["Phải thu khác", 50], ["B. TÀI SẢN DÀI HẠN", 500], ["I. Tài sản cố định", 500], ["Nguyên giá", 800], ["Hao mòn", -300], ["TỔNG CỘNG TÀI SẢN", 800]];
    const [check] = checkTableTotals(amounts(rows, "Số cuối kỳ"));
    expect(check.ok).toBe(true);
    expect(check.count).toBe(2);
  });

  it("gives no false flag for a heading that repeats its one row", () => {
    const rows = [["a) Trả trước cho người bán", 1241], ["Trả trước khách hàng khác", 1241], ["Cộng", 1241]];
    expect(checkTableTotals(amounts(rows)).filter((check) => !check.ok)).toEqual([]);
  });

  it("leaves lists of measures and ratios unchecked", () => {
    const ratio = [["Doanh thu", 9556], ["LNST", 1222], ["Tổng nợ/Vốn chủ (x)", 0.7]];
    expect(checkTableTotals(amounts(ratio))).toEqual([]);
    const mixed = [["Dòng tiền tự do", -1132], ["Vốn CSH", 9030], ["Nợ ròng / EBITDA (x)", 0.5], ["Tổng tài sản", 17490]];
    expect(checkTableTotals(amounts(mixed))).toEqual([]);
  });

  it("still flags a flat list that does not add up", () => {
    const [check] = checkTableTotals(amounts([["Bắc", 10], ["Trung", 20], ["Nam", 35], ["Tổng", 75]]));
    expect(check).toMatchObject({ ok: false, diff: 10, count: 3 });
  });

  it("accepts a total of only the rows just above it", () => {
    const [check] = checkTableTotals(amounts([["Khác", 999], ["Bắc", 10], ["Nam", 30], ["Cộng", 40]]));
    expect(check).toMatchObject({ ok: true, count: 2 });
  });

  it("knows which rows add into which", async () => {
    const { columnParents } = await import("./reportChecks.js");
    const cells = amounts([["I. Tiền", 100], ["Tiền mặt", 60], ["Tiền gửi", 40], ["II. Phải thu", 50], ["Khách hàng", 50]]);
    const parents = columnParents(cells);
    expect(parents.get("r1").evidence_key).toBe("r0");
    expect(parents.get("r2").evidence_key).toBe("r0");
    expect(parents.get("r4").evidence_key).toBe("r3");
    expect(parents.has("r0")).toBe(false);
  });
});

describe("readingCells", () => {
  const coded = (key, row, rowIndex, column, columnIndex, raw, value = raw) => ({ ...cell(key, row, rowIndex, column, columnIndex, Number(String(value).replace(/\D/g, "")), raw) });
  const evidences = [
    coded("n1", null, 1, "Mã số", 1, "2"), coded("n2", null, 1, "Thu yết min h", 2, "3"), coded("n3", null, 1, "Số cuối kỳ", 3, "4"), coded("n4", null, 1, "Số đầu năm", 4, "5"),
    coded("c1", "I. Tiền", 2, "Mã số", 1, "110"), coded("t1", "I. Tiền", 2, "Thuyết minh", 2, "V.01"), coded("v1", "I. Tiền", 2, "Số cuối kỳ", 3, "100"),
    coded("c2", null, 3, "Mã số", 1, "111"), coded("v2", null, 3, "Số cuối kỳ", 3, "60"),
  ];
  it("drops line codes, note numbers and the row of column numbers, and names rows by their code", async () => {
    const { readingCells } = await import("./reportChecks.js");
    const kept = readingCells(evidences);
    expect(kept.map((item) => item.evidence_key)).toEqual(["v1", "v2"]);
    expect(kept[1].table_locator.row_header).toBe("Mã số 111");
    expect(evidences[8].table_locator.row_header).toBeNull();
  });
});

describe("linkNumbers with equal values", () => {
  const bar = (key, label) => ({ kind: "data", page: 2, value: "38", raw_text: "38", label, evidence_key: key, bbox: [0.1, 0.1, 0.2, 0.2] });
  it("links each number to the cell the sentence names", () => {
    const answer = { evidence: [bar("north-1", "T1 · Miền Bắc"), bar("south-6", "T6 · Miền Nam")] };
    const chips = linkNumbers("Miền Bắc tháng 1 có 38, còn miền Nam tháng 6 là 38.", answer).filter((part) => part.chip);
    expect(chips.map((part) => part.chip.key)).toEqual(["north-1", "south-6"]);
  });
});

describe("period-only columns", () => {
  it("reads balance-sheet headers as periods and asks about the row", async () => {
    const { splitColumn, suggestQuestions, lowerFirst } = await import("./reportChecks.js");
    expect(splitColumn("Số cuối kỳ")).toEqual({ measure: "", period: "Số cuối kỳ" });
    expect(lowerFirst("BSC dự báo")).toBe("BSC dự báo");
    expect(lowerFirst("Doanh thu")).toBe("doanh thu");
    const cells = [cell("a", "I. Tiền", 1, "Số cuối kỳ", 1, 100), cell("b", "I. Tiền", 1, "Số đầu năm", 2, 80), cell("c", "II. Phải thu", 2, "Số cuối kỳ", 1, 50), cell("d", "II. Phải thu", 2, "Số đầu năm", 2, 40)];
    expect(suggestQuestions(cells)).toEqual(["Tiền cuối kỳ là bao nhiêu?", "Tiền thay đổi bao nhiêu từ đầu năm đến cuối kỳ?", "Mục nào lớn nhất cuối kỳ?"]);
  });
});
