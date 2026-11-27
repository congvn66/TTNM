// Pure helpers for the report canvas: read numbers written in Vietnamese or
// English style, link the numbers in an answer to their PDF source, and build
// the upload briefing from the extracted evidence list.
import { evidenceLabel as readableEvidenceLabel, needsCheck } from "./format.js";

export const TOTAL_ROW = /^(tổng cộng|tổng|cộng|total|grand total)\b/i;
export const NOT_ADDITIVE = /%|biên|tỷ lệ|tỉ lệ|margin|ratio|bình quân|trung bình|average|giá/i;

/** Every number a written token can mean ("1,234" is 1.234 in Vietnamese and 1234 in English). */
export function readNumberCandidates(text) {
  const token = String(text ?? "").replace(/[%\s]/g, "").replace(/^[+−-]/, (sign) => (sign === "+" ? "" : "-"));
  if (!/^-?\d[\d.,]*$/.test(token)) return [];
  const hasDot = token.includes(".");
  const hasComma = token.includes(",");
  const values = new Set();
  if (hasDot && hasComma) {
    const decimal = token.lastIndexOf(".") > token.lastIndexOf(",") ? "." : ",";
    const thousands = decimal === "." ? "," : ".";
    values.add(Number(token.split(thousands).join("").replace(decimal, ".")));
  } else if (hasDot || hasComma) {
    const separator = hasDot ? "." : ",";
    const grouped = new RegExp(`^-?\\d{1,3}(\\${separator}\\d{3})+$`).test(token);
    if (grouped) values.add(Number(token.split(separator).join("")));
    if (token.split(separator).length === 2) values.add(Number(token.replace(separator, ".")));
  } else {
    values.add(Number(token));
  }
  return [...values].filter(Number.isFinite);
}

function sameNumber(a, b) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  return Math.abs(a - b) <= Math.max(1e-9, Math.abs(b) * 1e-9);
}

function evidenceNumbers(item) {
  const values = [];
  if (item.value != null && item.value !== "") values.push(...readNumberCandidates(item.value));
  if (item.raw_text) values.push(...readNumberCandidates(item.raw_text));
  return values;
}

function chipFromEvidence(item) {
  return {
    page: item.page,
    boxes: item.bbox ? [item.bbox] : [],
    label: item.label || "",
    method: item.method_label || "",
    unsure: Boolean(item.data_status && item.data_status !== "valid"),
    key: item.evidence_key,
    raw: item.raw_text || "",
  };
}

/** Every number inside a calculation result, which may be a plain value or a small JSON object. */
export function resultNumbers(result) {
  return (String(result ?? "").match(/-?\d+(?:[.,]\d+)*/g) ?? []).flatMap(readNumberCandidates);
}

export function chipFromFormula(formula) {
  const inputs = (formula.inputs ?? []).filter((input) => input.page);
  if (!inputs.length) return null;
  const page = inputs[0].page;
  return {
    page,
    boxes: inputs.filter((input) => input.page === page && input.bbox).map((input) => input.bbox),
    // One part per input box, so each input gets its own colour and number on the page and in the bar.
    // index is the input's place in the whole calculation, the number on its tag.
    parts: (formula.inputs ?? []).map((input, index) => ({ value: formatNumber(Number(input.value)), label: input.label || "", key: input.evidence_key, index, page: input.page, bbox: input.bbox }))
      .filter((part) => part.page === page && part.bbox),
    label: `Tính từ ${inputs.map((input) => `${formatNumber(Number(input.value))}${input.label ? ` (${input.label})` : ""}`).join(" và ")}`,
    method: "phép tính",
    unsure: false,
    key: `formula-${formula.expression ?? formula.result}`,
    computed: true,
    formula,
  };
}

/**
 * Split answer text into plain runs and number chips. A number becomes a chip
 * only when it equals a value the answer itself cites, so dates and list
 * numbers stay plain text.
 */
export function linkNumbers(text, answer) {
  const source = String(text ?? "");
  const evidence = (answer?.evidence ?? []).filter((item) => item.kind === "data" && item.page);
  const formulas = (answer?.formulas ?? []).filter((formula) => formula.result != null);
  if (!source || (!evidence.length && !formulas.length)) return [{ text: source }];
  const pattern = /[+−-]?\d+(?:[.,]\d+)*(?:\s?%)?/g;
  const parts = [];
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    const start = match.index;
    const end = start + match[0].length;
    const before = source[start - 1];
    const after = source[end];
    if (before === "/" || after === "/" || /[\p{L}]/u.test(before ?? "")) continue;
    const candidates = readNumberCandidates(match[0]);
    let chip = null;
    const hit = evidence.find((item) => evidenceNumbers(item).some((value) => candidates.some((candidate) => sameNumber(candidate, value))));
    if (hit) chip = chipFromEvidence(hit);
    if (!chip) {
      const formula = formulas.find((item) => resultNumbers(item.result).some((value) => candidates.some((candidate) => sameNumber(candidate, value) || sameNumber(candidate, value * 100))));
      // Each calculated number is its own chip, so tapping one lights only that one.
      const base = formula ? chipFromFormula(formula) : null;
      // Which of the script's results this number is, so the bar can show its own formula.
      const row = formula && (formula.result_rows ?? []).find((item) => readNumberCandidates(String(item.value)).some((value) => candidates.some((candidate) => sameNumber(candidate, value) || sameNumber(candidate, value * 100))));
      if (base) chip = { ...base, key: `formula-${start}-${match[0]}`, result: row?.name ?? null };
    }
    if (!chip) continue;
    if (start > cursor) parts.push({ text: source.slice(cursor, start) });
    parts.push({ text: match[0], chip });
    cursor = end;
  }
  if (cursor < source.length) parts.push({ text: source.slice(cursor) });
  return parts.length ? parts : [{ text: source }];
}

function evidenceLabel(evidence) {
  return readableEvidenceLabel(evidence);
}

function toChip(evidence, extra = {}) {
  return { page: evidence.page_number, boxes: evidence.bbox ? [evidence.bbox] : [], label: evidenceLabel(evidence), method: evidence.method_label || "", key: evidence.evidence_key, ...extra };
}

function decimals(evidence) {
  const raw = String(evidence.raw_text ?? "");
  const match = raw.match(/[.,](\d{1,2})%?$/);
  return match && !/^\d{1,3}([.,]\d{3})+$/.test(raw.replace(/%/g, "")) ? match[1].length : 0;
}

export function formatNumber(value) {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
}

const isTotal = (cell) => TOTAL_ROW.test(String(cell.table_locator?.row_header ?? "").trim());

/**
 * The total rows of one table column, each with the rows it adds up: the rows
 * between the previous total row and this one. A table with subtotals
 * ("Tổng A" after A rows, "Tổng B" after B rows) gives one group per subtotal.
 */
export function totalGroups(columnCells) {
  const sorted = [...columnCells].sort((a, b) => a.table_locator.row_index - b.table_locator.row_index);
  const groups = [];
  let parts = [];
  for (const cell of sorted) {
    if (isTotal(cell)) { groups.push({ total: cell, parts }); parts = []; }
    else if (!NOT_ADDITIVE.test(cell.table_locator.row_header ?? "")) parts.push(cell);
  }
  return groups;
}

/** Column totals that should equal the rows they add up. */
export function checkTableTotals(evidences) {
  const tables = new Map();
  for (const evidence of evidences ?? []) {
    const locator = evidence.table_locator;
    if (!locator?.table_region_key || locator.column_index == null) continue;
    const key = `${locator.table_region_key}::${locator.column_index}`;
    if (!tables.has(key)) tables.set(key, []);
    tables.get(key).push(evidence);
  }
  const checks = [];
  for (const cells of tables.values()) {
    const column = cells[0].table_locator.column_header ?? "";
    if (NOT_ADDITIVE.test(column)) continue;
    for (const { total, parts } of totalGroups(cells)) {
      if (parts.length < 2) continue;
      const totalValue = Number(total.current_numeric_value);
      const values = parts.map((cell) => Number(cell.current_numeric_value));
      if (total.current_numeric_value == null || parts.some((cell) => cell.current_numeric_value == null) || !Number.isFinite(totalValue) || values.some((value) => !Number.isFinite(value))) continue;
      const sum = values.reduce((acc, value) => acc + value, 0);
      const unit = 10 ** -Math.max(...[total, ...parts].map(decimals));
      const tolerance = 0.5 * unit * parts.length + 1e-9;
      const diff = totalValue - sum;
      const page = total.page_number;
      checks.push({
        ok: Math.abs(diff) <= tolerance,
        column,
        total: totalValue,
        sum,
        diff,
        count: parts.length,
        keys: [total, ...parts].map((cell) => cell.evidence_key),
        chip: { page, boxes: [total, ...parts].filter((cell) => cell.page_number === page && cell.bbox).map((cell) => cell.bbox), label: `${column}: ${parts.length} dòng và dòng tổng`, method: "kiểm tra tổng", key: `total-${total.evidence_key}` },
      });
    }
  }
  return checks;
}

/** What the upload briefing shows, built only from what extraction found. */
export function buildBriefing(evidences) {
  const list = evidences ?? [];
  const tableCells = list.filter((evidence) => evidence.table_locator?.table_region_key);
  const tables = new Set(tableCells.map((evidence) => evidence.table_locator.table_region_key));
  const pages = new Set(list.map((evidence) => evidence.page_number).filter(Boolean));
  const checks = checkTableTotals(list);
  const blank = (evidence) => /^[\s\-–—.]*$/.test(String(evidence.raw_text ?? ""));
  // "missing" is the report's own no-data mark ("—"); unreadable and ambiguous readings need a check.
  const missing = tableCells
    .filter((evidence) => evidence.current_numeric_value == null && (evidence.data_status === "missing" || (blank(evidence) && !needsCheck(evidence.data_status))) && evidence.table_locator.row_header && evidence.table_locator.column_header)
    .map((evidence) => toChip(evidence, { raw: evidence.raw_text }));
  const unreadable = tableCells
    .filter((evidence) => evidence.current_numeric_value == null && evidence.data_status !== "missing" && (needsCheck(evidence.data_status) || !blank(evidence)))
    .map((evidence) => toChip(evidence, { raw: evidence.raw_text }));
  const scanned = list.some((evidence) => /ocr|scan|ảnh/i.test(`${evidence.method_label ?? ""} ${evidence.extraction_method ?? ""}`));
  const unsure = list
    .filter((evidence) => evidence.current_numeric_value != null && ((evidence.data_status && evidence.data_status !== "valid") || (evidence.chart_read && Number(evidence.confidence ?? 1) < 0.8)))
    .map((evidence) => toChip(evidence, { value: Number(evidence.current_numeric_value) }));
  return {
    numberCount: list.filter((evidence) => evidence.current_numeric_value != null).length,
    tableCount: tables.size,
    pageCount: pages.size,
    checks,
    missing,
    unreadable,
    unsure,
    scanned,
    suggestions: suggestQuestions(tableCells),
    unchecked: uncheckedTotals(list),
    tableNumberCount: tableCells.filter((evidence) => evidence.current_numeric_value != null).length,
  };
}

// Letter lookahead, not \b: \b does not count "ý" or "ă" as letters, so "quý" never matched.
const PERIOD = /^(quý|q|tháng|năm|nửa|6 tháng|9 tháng|cuối|đầu|fy|h[12])(?!\p{L})/iu;
const NOT_A_MEASURE = /chú thích|ghi chú|đơn vị|nguồn|note|source|unit|stt|^tt$/i;
const NAME_OK = (text) => {
  const value = String(text ?? "").trim();
  return value.length >= 2 && value.length <= 40 && /^\p{L}/u.test(value) && !NOT_A_MEASURE.test(value)
    && !/vnd|usd|%|\(x\)|\+|\d{3,}|[=:;]/i.test(value.replace(/\d{1,2}\/\d{4}|\b\d{4}\b/g, ""));
};
const lowerFirst = (text) => text.charAt(0).toLocaleLowerCase("vi") + text.slice(1);

/** A column header split into what is measured and for which period ("Doanh thu thuần · Quý 2/2026"). */
export function splitColumn(header) {
  // "Doanh thu · Quý 2/2026", or "Doanh thu / Quý 2/2026" when a period word follows the slash.
  // "Quý 1 / 2026", "EV / EBITDA" and "Nợ / Vốn chủ sở hữu" stay whole.
  const parts = String(header ?? "").split(" · ").flatMap((part) => {
    const at = part.lastIndexOf(" / ");
    return at > 0 && PERIOD.test(part.slice(at + 3).trim()) ? [part.slice(0, at), part.slice(at + 3)] : [part];
  }).map((part) => part.trim()).filter(Boolean);
  const period = parts.find((part) => PERIOD.test(part) || /\d{1,2}\/\d{4}|(?<!\d)20\d{2}(?=[EeFf]?(?![\p{L}\d]))/u.test(part)) ?? "";
  const measure = parts.filter((part) => part !== period).join(" ");
  return { measure, period };
}

/**
 * Up to three starter questions written from one table's own headers, in
 * natural Vietnamese. A table whose headers do not read like words gives none:
 * no suggestion is better than a strange one.
 */
export function suggestQuestions(tableCells) {
  const usable = tableCells.filter((cell) => cell.current_numeric_value != null && NAME_OK(cell.table_locator.row_header) && NAME_OK(splitColumn(cell.table_locator.column_header).measure));
  if (!usable.length) return measureRowQuestions(tableCells);
  // Prefer the table whose columns carry periods: its questions read most naturally.
  const score = new Map();
  for (const cell of usable) {
    const key = cell.table_locator.table_region_key;
    score.set(key, (score.get(key) ?? 0) + (splitColumn(cell.table_locator.column_header).period ? 2 : 1));
  }
  const tableKey = [...score.entries()].sort((a, b) => b[1] - a[1])[0][0];
  const table = usable.filter((cell) => cell.table_locator.table_region_key === tableKey);
  const rows = [...new Set(table.map((cell) => cell.table_locator.row_header.trim()))];
  const columns = [...new Set(table.map((cell) => cell.table_locator.column_header))].map(splitColumn);
  const questions = [];
  const plainRow = rows.find((row) => !TOTAL_ROW.test(row));
  const first = columns[0];
  if (plainRow) questions.push(`${first.measure}${first.period ? ` ${first.period}` : ""} của ${plainRow} là bao nhiêu?`);
  const periods = columns.filter((column) => column.measure === first.measure && column.period);
  const totalRow = rows.find((row) => TOTAL_ROW.test(row));
  if (periods.length >= 2) {
    const subject = totalRow ? `Tổng ${lowerFirst(first.measure)}` : `${first.measure} của ${plainRow ?? rows[0]}`;
    questions.push(`${subject} thay đổi bao nhiêu từ ${periods[0].period} đến ${periods.at(-1).period}?`);
  }
  if (rows.filter((row) => !TOTAL_ROW.test(row)).length >= 2) {
    const last = periods.at(-1) ?? first;
    questions.push(`Mục nào có ${lowerFirst(first.measure)}${last.period ? ` ${last.period}` : ""} cao nhất?`);
  }
  return questions.filter((question) => question.length <= 100);
}

const YEAR = /^(19|20)\d{2}(F|E)?$/i;
const yearWords = (header) => { const value = String(header).trim(); return /[FE]$/i.test(value) ? `năm ${value.slice(0, 4)} (dự phóng)` : `năm ${value}`; };
// Drop only brackets that hold a unit ("(tỷ VND)", "(%)"); keep ones that are part of the name ("Lãi/(lỗ)").
const withoutUnit = (text) => String(text ?? "").replace(/\s*\((?=[^)]*(vnd|usd|tỷ|triệu|nghìn|đồng|%|\bx\b))[^)]*\)\s*/gi, " ").trim();

/** Questions for tables whose rows are measures and whose columns are years, as in broker forecasts. */
function measureRowQuestions(tableCells) {
  const cells = tableCells.filter((cell) => cell.current_numeric_value != null && YEAR.test(String(cell.table_locator.column_header ?? "").trim()) && NAME_OK(withoutUnit(cell.table_locator.row_header)));
  if (!cells.length) return [];
  const tableKey = cells[0].table_locator.table_region_key;
  const table = cells.filter((cell) => cell.table_locator.table_region_key === tableKey);
  const rows = [...new Set(table.map((cell) => withoutUnit(cell.table_locator.row_header)))];
  const years = [...new Set(table.map((cell) => String(cell.table_locator.column_header).trim()))];
  const questions = [`${rows[0]} ${yearWords(years.at(-1))} là bao nhiêu?`];
  if (years.length >= 2) questions.push(`${rows[0]} thay đổi bao nhiêu từ ${yearWords(years[0])} đến ${yearWords(years.at(-1))}?`);
  if (rows[1]) questions.push(`${rows[1]} ${yearWords(years.at(-1))} là bao nhiêu?`);
  return questions.filter((question) => question.length <= 100);
}

/** Columns with a total row that cannot be checked because some cells have no number. */
export function uncheckedTotals(evidences) {
  const columns = new Map();
  for (const evidence of evidences ?? []) {
    const locator = evidence.table_locator;
    if (!locator?.table_region_key || locator.column_index == null) continue;
    const key = `${locator.table_region_key}::${locator.column_index}`;
    if (!columns.has(key)) columns.set(key, []);
    columns.get(key).push(evidence);
  }
  const result = [];
  for (const cells of columns.values()) {
    const column = cells[0].table_locator.column_header ?? "";
    if (NOT_ADDITIVE.test(column) || !cells.some((cell) => TOTAL_ROW.test(String(cell.table_locator.row_header ?? "").trim()))) continue;
    const empty = cells.filter((cell) => cell.current_numeric_value == null).length;
    if (empty) result.push({ column, empty });
  }
  return result;
}
