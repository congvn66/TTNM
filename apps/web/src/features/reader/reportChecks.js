// Pure helpers for the report canvas: read numbers written in Vietnamese or
// English style, link the numbers in an answer to their PDF source, and build
// the upload briefing from the extracted evidence list.
import { evidenceLabel as readableEvidenceLabel, needsCheck } from "./format.js";

export const NOT_ADDITIVE = /%|biên|tỷ lệ|tỉ lệ|margin|ratio|bình quân|trung bình|average|giá/i;

/** Text without Vietnamese accents, for names that scans read with lost or wrong accents. */
export const withoutAccents = (text) => String(text ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D");

// A row of ratios or per-share figures: never a part of a sum, and never a total ("Tổng nợ/Vốn chủ (x)").
// "/" counts only before a base ("/cp", "/ VCSH", "/EBITDA"), so "Tăng/giảm" and "Lãi/(lỗ)" stay amounts.
const RATIO_ROW = /%|\((?:x|lần)\)|(?<!\p{L})(?:lần|biên|tỷ lệ|tỉ lệ|tỷ suất|tỉ suất|margin|ratio|bình quân|trung bình|average|eps|roe|roa|roic|wacc|per|pbr|psr|p\/e|p\/b)(?!\p{L})|\/\s*(?:vốn|vcsh|ebitda|ebit|doanh thu|cp|cổ phiếu|tài sản|tổng|lnst|equity|assets|sales|fcf)(?!\p{L})/iu;
export const isRatioRow = (name) => RATIO_ROW.test(String(name ?? ""));

/**
 * A row name that says "the rows above add up to this": "Tổng", "Cộng", "Tổng cộng tài sản".
 * Scans give "Téng", "TONG CONG TAI SAN" or "“Tổng": leading marks are dropped and accents compared loosely.
 * "Cong" counts only when written without accents, so "Công ty" stays a name.
 */
export function isTotalName(name) {
  const text = String(name ?? "").trim().replace(/^[^\p{L}\p{N}]+/u, "").normalize("NFC").toLocaleLowerCase("vi");
  if (!text || isRatioRow(text)) return false;
  if (/^(?:tổng cộng|tổng|cộng|total|grand total)(?!\p{L})/u.test(text)) return true;
  return /^t[oe]ng(?![a-z])/.test(withoutAccents(text)) || /^cong(?![a-z])/.test(text);
}

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

// Words a label and an answer write differently: "T6" is "tháng 6", "Q2" is "quý 2".
const labelWords = (label) => String(label ?? "").split(" · ").map((part) => part.trim().toLocaleLowerCase("vi")
  .replace(/^t(\d{1,2})$/, "tháng $1").replace(/^q([1-4])$/, "quý $1")).filter(Boolean);

/**
 * Several cited cells have the value written in the answer ("38" for both T1 Miền Bắc and
 * T6 Miền Nam): take the one whose label the answer names just before the number, first in
 * the words since the previous number, then in the whole sentence. A tie goes to a cell not
 * linked yet, so a list of equal numbers marks different cells.
 */
function closestByLabel(hits, text, start, cursor, used) {
  const near = text.slice(cursor, start).toLocaleLowerCase("vi");
  const sentence = text.slice(Math.max(0, text.lastIndexOf(". ", start - 1) + 1, start - 160), start).toLocaleLowerCase("vi");
  const score = (item) => labelWords(item.label).reduce((acc, word) => acc + (near.includes(word) ? 3 : sentence.includes(word) ? 1 : 0), 0) - (used.has(item.evidence_key) ? 0.5 : 0);
  return hits.reduce((best, item) => (score(item) > score(best) ? item : best), hits[0]);
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
  const used = new Set();
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    const start = match.index;
    const end = start + match[0].length;
    const before = source[start - 1];
    const after = source[end];
    if (before === "/" || after === "/" || /[\p{L}]/u.test(before ?? "")) continue;
    const candidates = readNumberCandidates(match[0]);
    let chip = null;
    const hits = evidence.filter((item) => evidenceNumbers(item).some((value) => candidates.some((candidate) => sameNumber(candidate, value))));
    const hit = hits.length > 1 ? closestByLabel(hits, source, start, cursor, used) : hits[0];
    if (hit) { chip = chipFromEvidence(hit); used.add(hit.evidence_key); }
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

const isTotal = (cell) => isTotalName(cell.table_locator?.row_header);
const amount = (cell) => (cell.current_numeric_value == null ? null : Number(cell.current_numeric_value));
// Percentages and multiples ("0,7 lần") never add up into a total.
const isPercentCell = (cell) => ["PERCENT", "TIMES"].includes(cell.semantic?.unit) || String(cell.raw_text ?? "").includes("%");
// "a) Trả trước", "I. Tiền", "1. Doanh thu", "TÀI SẢN NGẮN HẠN" or no name at all: a heading that may stand for its rows below.
const HEADING = /^(?:[ivxlc]+|[a-zđ]|\d+(?:\.\d+)*)[.)]\s/iu;
const headingLike = (cell) => {
  const name = String(cell.table_locator?.row_header ?? "").trim();
  return !name || HEADING.test(name) || (/\p{Lu}{3}/u.test(name) && name === name.toLocaleUpperCase("vi"));
};
const unitHint = (cell) => String(cell.table_locator?.row_header ?? "").match(/\(([^)]*(?:vnd|usd|tỷ|triệu|nghìn|đồng|cp|lần|x))[^)]*\)/i)?.[1]?.toLowerCase() ?? null;

/**
 * Rows that add up into a row next to them, as in a balance sheet: "I. Tiền" over its two rows,
 * "Thu nhập lãi thuần" under "Thu nhập lãi" and "Chi phí lãi". Innermost first: headings are
 * folded from the bottom up (a heading's own sub-headings sit below it), subtotals that follow
 * their rows from the top down. A single row under a heading counts too.
 * Returns the top level left after folding, each item with the rows folded into it.
 */
function nestRows(items, tolerance) {
  const list = items.map((item) => ({ ...item, kids: [] }));
  const fold = (at, from, to) => {
    list[at].kids = [...list[at].kids, ...list.slice(from, to + 1)];
    list.splice(from, to - from + 1);
  };
  const under = () => {
    for (let i = list.length - 2; i >= 0; i -= 1) {
      if (!list[i].value) continue;
      let sum = 0;
      for (let j = i + 1; j < list.length && j - i <= 40; j += 1) {
        sum += list[j].value;
        if ((j - i >= 2 || headingLike(list[i].cell)) && Math.abs(sum - list[i].value) <= tolerance(j - i)) { fold(i, i + 1, j); return true; }
      }
    }
    return false;
  };
  const after = () => {
    for (let i = 2; i < list.length; i += 1) {
      if (!list[i].value) continue;
      let sum = 0;
      for (let k = i - 1; k >= 0 && i - k <= 40; k -= 1) {
        sum += list[k].value;
        if (i - k >= 2 && Math.abs(sum - list[i].value) <= tolerance(i - k)) { fold(i, k, i - 1); return true; }
      }
    }
    return false;
  };
  let changed = false;
  for (let guard = 0; guard < 400; guard += 1) {
    if (!under() && !after()) break;
    changed = true;
  }
  return { list, changed };
}

// Digits after the decimal mark in the printed number, so "482,0" is checked to 0,1 and "38.770" to 1.
function toleranceFor(cells) {
  const unit = 10 ** -Math.max(0, ...cells.map(decimals));
  return (count) => 0.5 * unit * Math.max(1, count) + 1e-9;
}

/**
 * Whether a total row equals the rows it adds up. Statements nest: subtotals sit among their
 * own parts, and headings repeat the sum of the rows under them. So the plain sum is tried
 * first, then the sum once nested rows are folded, then the last few rows alone. A mismatch is
 * reported only for a flat list; when rows nest and nothing fits, the total is left unchecked,
 * because a wrong "không khớp" costs more than a missing one.
 */
function judgeTotal(total, parts) {
  const tolerance = toleranceFor([total, ...parts]);
  const target = amount(total);
  const items = parts.map((cell) => ({ cell, value: amount(cell) }));
  const sum = (list) => list.reduce((acc, item) => acc + item.value, 0);
  if (Math.abs(sum(items) - target) <= tolerance(items.length)) return { status: "ok", parts, sum: sum(items) };
  const { list, changed } = nestRows(items, tolerance);
  if (changed && Math.abs(sum(list) - target) <= tolerance(list.length)) return { status: "ok", parts: list.map((item) => item.cell), sum: sum(list) };
  // Only the rows just above the total: an earlier block with no total row of its own.
  for (let start = list.length - 2; start > 0; start -= 1) {
    const tail = list.slice(start);
    if (Math.abs(sum(tail) - target) <= tolerance(tail.length)) return { status: "ok", parts: tail.map((item) => item.cell), sum: sum(tail) };
  }
  if (changed) return { status: "unclear", parts: list.map((item) => item.cell), sum: sum(list) };
  return { status: "bad", parts, sum: sum(items) };
}

/**
 * The total rows of one table column, each with the rows it adds up: the rows
 * between the previous total row and this one, folded where they nest. A group whose
 * rows hold ratios, percentages or mixed units is a list of measures, not a sum: it is
 * left out. status is "ok", "bad" or "unclear" (rows nest and no reading of them fits).
 */
export function totalGroups(columnCells) {
  const sorted = [...columnCells].sort((a, b) => a.table_locator.row_index - b.table_locator.row_index);
  const groups = [];
  let span = [];
  for (const cell of sorted) {
    if (!isTotal(cell)) { span.push(cell); continue; }
    const rows = span;
    span = [];
    const parts = rows;
    const units = new Set([cell, ...parts].map((other) => other.semantic?.unit).filter(Boolean));
    const hints = new Set([cell, ...parts].map(unitHint).filter(Boolean));
    if (rows.some((other) => isRatioRow(other.table_locator.row_header)) || [cell, ...parts].some(isPercentCell) || units.size > 1 || hints.size > 1) continue;
    if (amount(cell) == null || !Number.isFinite(amount(cell)) || parts.length < 2 || parts.some((other) => amount(other) == null || !Number.isFinite(amount(other)))) {
      groups.push({ total: cell, parts, status: "unchecked" });
      continue;
    }
    groups.push({ total: cell, ...judgeTotal(cell, parts) });
  }
  return groups;
}

/**
 * Which row each row of a column adds into: its total row, or the heading or subtotal it is
 * folded under. Used to warn when a selection adds a row together with the row it is part of.
 */
export function columnParents(columnCells) {
  const parents = new Map();
  const sorted = [...columnCells].filter((cell) => amount(cell) != null && Number.isFinite(amount(cell))).sort((a, b) => a.table_locator.row_index - b.table_locator.row_index);
  const link = (item) => item.kids.forEach((kid) => { parents.set(kid.cell.evidence_key, item.cell); link(kid); });
  let span = [];
  const fold = (total) => {
    const rows = span.filter((cell) => !isRatioRow(cell.table_locator.row_header) && !isPercentCell(cell));
    span = [];
    const { list } = nestRows(rows.map((cell) => ({ cell, value: amount(cell) })), toleranceFor(rows));
    list.forEach(link);
    if (total) list.forEach((item) => parents.set(item.cell.evidence_key, total));
  };
  for (const cell of sorted) {
    if (isTotal(cell)) fold(cell); else span.push(cell);
  }
  fold(null);
  return parents;
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
    for (const { total, parts, status, sum } of totalGroups(cells)) {
      if ((status !== "ok" && status !== "bad") || parts.length < 2) continue;
      const totalValue = amount(total);
      const diff = totalValue - sum;
      const page = total.page_number;
      const name = column || total.table_locator.row_header || "Bảng";
      checks.push({
        ok: status === "ok",
        column: name,
        total: totalValue,
        sum,
        diff,
        count: parts.length,
        keys: [total, ...parts].map((cell) => cell.evidence_key),
        chip: { page, boxes: [total, ...parts].filter((cell) => cell.page_number === page && cell.bbox).map((cell) => cell.bbox), label: `${name}: ${parts.length} dòng và dòng tổng`, method: "kiểm tra tổng", key: `total-${total.evidence_key}` },
      });
    }
  }
  return checks;
}

// Columns that hold a line code or a note number, not an amount: "Mã số", "Thuyết minh" (scans give "Mã Á sô", "Thu yết min h").
const squash = (text) => withoutAccents(text).toLowerCase().replace(/[^a-z0-9]/g, "");
const REFERENCE_COLUMN = /^(?:ma.{0,2}so|maso|thu.{0,4}minh?|tm|code|codes|notes?|stt|sott)$/;
export const isReferenceColumn = (header) => REFERENCE_COLUMN.test(squash(header));
// A note number such as "V.01" or "VI.25".
const NOTE_NUMBER = /^[ivx]+\.\d+[a-z]?$/i;

/**
 * The cells a reader can use as amounts. Line codes, note numbers and the row of column
 * numbers under the header ("1 2 3 4 5") are dropped: they are labels, not values to tap,
 * add up or chart. A row with no name of its own but a line code is named after the code
 * ("Mã số 111"), the way the statement itself refers to it.
 */
export function readingCells(evidences) {
  const list = evidences ?? [];
  const rows = new Map();
  for (const cell of list) {
    const locator = cell.table_locator;
    if (!locator?.table_region_key) continue;
    const key = `${cell.page_number}::${locator.table_region_key}::${locator.row_index}`;
    if (!rows.has(key)) rows.set(key, []);
    rows.get(key).push(cell);
  }
  const firstRow = new Map();
  for (const cell of list) {
    const locator = cell.table_locator;
    if (!locator?.table_region_key) continue;
    const key = `${cell.page_number}::${locator.table_region_key}`;
    firstRow.set(key, Math.min(firstRow.get(key) ?? Infinity, locator.row_index));
  }
  // A scan may lose the header ("on", "Ma sé"): a column of short whole numbers that climb row by row is a code column.
  const columns = new Map();
  for (const cell of list) {
    const locator = cell.table_locator;
    if (!locator?.table_region_key) continue;
    const key = `${cell.page_number}::${locator.table_region_key}::${locator.column_index}`;
    if (!columns.has(key)) columns.set(key, []);
    columns.get(key).push(cell);
  }
  const codeColumns = new Set();
  for (const [key, cells] of columns) {
    const ordered = [...cells].sort((a, b) => a.table_locator.row_index - b.table_locator.row_index);
    const codes = ordered.filter((cell) => /^\d{2,3}[a-z]?$/i.test(String(cell.raw_text ?? "").trim())).map((cell) => parseInt(cell.raw_text, 10));
    const climbs = codes.slice(1).filter((code, index) => code > codes[index]).length;
    if (isReferenceColumn(cells[0].table_locator.column_header) || (codes.length >= 4 && codes.length >= ordered.length * 0.8 && climbs >= (codes.length - 1) * 0.9)) codeColumns.add(key);
  }
  const isCode = (cell) => codeColumns.has(`${cell.page_number}::${cell.table_locator.table_region_key}::${cell.table_locator.column_index}`);
  const drop = new Set();
  const names = new Map();
  for (const [key, cells] of rows) {
    const ordered = [...cells].sort((a, b) => a.table_locator.column_index - b.table_locator.column_index);
    const numbers = ordered.map((cell) => String(cell.raw_text ?? "").replace(/[\s()]/g, ""));
    const counting = numbers.length >= 2 && numbers.every((raw, index) => /^\d{1,2}$/.test(raw) && (index === 0 || Number(raw) === Number(numbers[index - 1]) + 1));
    const top = ordered[0].table_locator.row_index === firstRow.get(key.split("::").slice(0, 2).join("::"));
    if (counting && !ordered[0].table_locator.row_header && (numbers.length >= 3 || top)) { ordered.forEach((cell) => drop.add(cell.evidence_key)); continue; }
    const code = ordered.find((cell) => isCode(cell) && /^\d{2,3}[a-z]?$/i.test(String(cell.raw_text ?? "").trim()));
    if (code && !String(ordered[0].table_locator.row_header ?? "").trim()) names.set(key, `Mã số ${String(code.raw_text).trim()}`);
  }
  return list.filter((cell) => {
    const locator = cell.table_locator;
    if (!locator?.table_region_key) return true;
    return !drop.has(cell.evidence_key) && !isCode(cell) && !NOTE_NUMBER.test(String(cell.raw_text ?? "").trim());
  }).map((cell) => {
    const name = cell.table_locator && names.get(`${cell.page_number}::${cell.table_locator.table_region_key}::${cell.table_locator.row_index}`);
    return name ? { ...cell, table_locator: { ...cell.table_locator, row_header: name } } : cell;
  });
}

/** What the upload briefing shows, built only from what extraction found. */
export function buildBriefing(evidences) {
  const list = readingCells(evidences);
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
// Headers that name only a period, as balance sheets do: "Số cuối kỳ", "Số đầu năm", "Kỳ này".
const PERIOD_ONLY = /^(?:số\s+)?(?:cuối|đầu)\s+(?:kỳ|năm|quý|tháng)|^(?:kỳ|quý|năm)\s+(?:này|trước|nay)|^cùng kỳ/iu;
const NOT_A_MEASURE = /chú thích|ghi chú|đơn vị|nguồn|note|source|unit|stt|^tt$/i;
const NAME_OK = (text) => {
  const value = String(text ?? "").trim();
  return value.length >= 2 && value.length <= 40 && /^\p{L}/u.test(value) && !NOT_A_MEASURE.test(value)
    && !/vnd|usd|%|\(x\)|\+|\d{3,}|[=:;]/i.test(value.replace(/\d{1,2}\/\d{4}|\b\d{4}\b/g, ""));
};
// "Doanh thu" becomes "doanh thu", but "BSC dự báo" and "EBITDA" keep their capitals.
export const lowerFirst = (text) => (/^\p{Lu}{2}/u.test(text) ? text : text.charAt(0).toLocaleLowerCase("vi") + text.slice(1));

/**
 * Where a period sits in time, to tell which of two columns came first:
 * year × 100 + month the period ends in. Vietnamese statements often put the
 * current period on the left, so the page order cannot be trusted.
 * Null when the header gives no way to tell.
 */
export function periodRank(period) {
  const text = String(period ?? "").toLowerCase();
  // "Lũy kế từ đầu năm đến cuối quý này · Năm trước": the last word decides, so "năm nay/trước" before "đầu năm".
  if (/năm trước|kỳ trước|cùng kỳ/.test(text)) return 0;
  if (/năm nay|kỳ này/.test(text)) return 1;
  if (/đầu năm|đầu kỳ/.test(text)) return 0;
  if (/cuối năm|cuối kỳ/.test(text)) return 1;
  // "2026E" and "2026F" are estimate and forecast years in broker reports.
  // "9M2024" and "Q3/2024" glue the year to letters, so no \b before it.
  const year = Number(text.match(/(?<!\d)(?:19|20)\d{2}(?=[ef]?(?![\p{L}\d]))/u)?.[0] ?? (text.match(/\/(\d{2})\b/) ? `20${text.match(/\/(\d{2})\b/)[1]}` : NaN));
  if (!Number.isFinite(year)) return null;
  const quarter = text.match(/(?:quý|q)\s*([1-4])/)?.[1];
  const month = text.match(/tháng\s*(\d{1,2})\b/)?.[1];
  const end = quarter ? Number(quarter) * 3 : month && !/\d\s*tháng/.test(text) ? Number(month) : /6 tháng|6\s*m|h1|nửa đầu/.test(text) ? 6 : /9 tháng|9\s*m/.test(text) ? 9 : 12;
  return year * 100 + end;
}

/** A column header split into what is measured and for which period ("Doanh thu thuần · Quý 2/2026"). */
export function splitColumn(header) {
  // "Doanh thu · Quý 2/2026", or "Doanh thu / Quý 2/2026" when a period word follows the slash.
  // "Quý 1 / 2026", "EV / EBITDA" and "Nợ / Vốn chủ sở hữu" stay whole.
  const parts = String(header ?? "").split(" · ").flatMap((part) => {
    const at = part.lastIndexOf(" / ");
    return at > 0 && PERIOD.test(part.slice(at + 3).trim()) ? [part.slice(0, at), part.slice(at + 3)] : [part];
  }).map((part) => part.trim()).filter(Boolean);
  const period = parts.find((part) => PERIOD.test(part) || PERIOD_ONLY.test(part) || /\d{1,2}\/\d{4}|(?<!\d)20\d{2}(?=[EeFf]?(?![\p{L}\d]))/u.test(part)) ?? "";
  const measure = parts.filter((part) => part !== period).join(" ");
  return { measure, period };
}

/**
 * Up to three starter questions written from one table's own headers, in
 * natural Vietnamese. A table whose headers do not read like words gives none:
 * no suggestion is better than a strange one.
 */
/** A row name without its list mark, for a sentence: "I. Tiền và …" reads "Tiền và …". */
export const rowWords = (name) => String(name ?? "").trim().replace(/^(?:[ivxlc]+|[a-zđ]|\d+(?:\.\d+)*)[.)]\s+/iu, "").replace(/^[-–•+]\s*/, "");
// "Số cuối kỳ" in a sentence is "cuối kỳ".
export const periodWords = (period) => lowerFirst(String(period ?? "").replace(/^số\s+/iu, ""));
/** Periods earliest first, by what they say; page order when they do not say. */
export function byTime(periods) {
  const ranks = periods.map((item) => periodRank(item.period));
  if (ranks.some((rank) => rank == null)) return periods;
  return periods.map((item, index) => ({ item, rank: ranks[index], index })).sort((a, b) => a.rank - b.rank || a.index - b.index).map((entry) => entry.item);
}

export function suggestQuestions(tableCells) {
  const usable = tableCells.filter((cell) => {
    const { measure, period } = splitColumn(cell.table_locator.column_header);
    // A row named only by its line code ("Mã số 111") makes no question a person would ask.
    return cell.current_numeric_value != null && NAME_OK(cell.table_locator.row_header) && !/^mã số\s/i.test(cell.table_locator.row_header) && (NAME_OK(measure) || (!measure && PERIOD_ONLY.test(period)));
  });
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
  const plainRow = rows.find((row) => !isTotalName(row));
  const first = columns[0];
  // A balance sheet's columns name only periods ("Số cuối kỳ"): the row is then the measure.
  const of = (row, column) => (column.measure ? `${column.measure}${column.period ? ` ${column.period}` : ""} của ${rowWords(row)}` : `${rowWords(row)} ${periodWords(column.period)}`);
  if (plainRow) questions.push(`${of(plainRow, first)} là bao nhiêu?`);
  const periods = byTime(columns.filter((column) => column.measure === first.measure && column.period));
  const totalRow = rows.find((row) => isTotalName(row));
  if (periods.length >= 2) {
    const from = periods[0].period;
    const to = periods.at(-1).period;
    const subject = first.measure ? (totalRow ? `Tổng ${lowerFirst(first.measure)}` : `${first.measure} của ${rowWords(plainRow ?? rows[0])}`) : rowWords(totalRow ?? plainRow ?? rows[0]);
    questions.push(`${subject} thay đổi bao nhiêu từ ${first.measure ? from : periodWords(from)} đến ${first.measure ? to : periodWords(to)}?`);
  }
  if (rows.filter((row) => !isTotalName(row)).length >= 2) {
    const last = periods.at(-1) ?? first;
    questions.push(first.measure
      ? `Mục nào có ${lowerFirst(first.measure)}${last.period ? ` ${last.period}` : ""} cao nhất?`
      : `Mục nào lớn nhất ${periodWords(last.period)}?`);
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
    if (NOT_ADDITIVE.test(column) || !cells.some(isTotal)) continue;
    const empty = cells.filter((cell) => cell.current_numeric_value == null).length;
    if (empty) result.push({ column, empty });
  }
  return result;
}
