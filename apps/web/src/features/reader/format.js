// Display helpers for numbers and data labels. The API stores numbers as
// canonical decimal strings ("21350", "17.05"); users read Vietnamese style
// ("21.350", "17,05").

const DECIMAL = /^-?\d+(\.\d+)?$/;

// A number shows the digits it has: trailing zeros of the fraction add
// nothing ("5400.20" is 5.400,2), the rest are kept as they are.
export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "";
  const text = String(value).trim();
  if (!DECIMAL.test(text)) return text;
  const negative = text.startsWith("-");
  const [integer, rawFraction] = text.replace("-", "").split(".");
  const fraction = rawFraction?.replace(/0+$/, "");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${negative ? "-" : ""}${grouped}${fraction ? `,${fraction}` : ""}`;
}

/** True when both are numbers and they are not equal ("1300" vs "1300.0" are equal). */
export function numbersDiffer(first, second) {
  if (first === null || first === undefined || second === null || second === undefined) return false;
  const a = String(first).trim();
  const b = String(second).trim();
  if (!DECIMAL.test(a) || !DECIMAL.test(b)) return a !== b;
  return Number(a) !== Number(b);
}

const isEmpty = (value) => value === null || value === undefined || value === "";

/**
 * True when a value is not the number first read from the PDF: a user edit.
 * A number the reading could not get (no original) differs from any value.
 */
export function differsFromReading(value, original) {
  return !isEmpty(value) && (isEmpty(original) || numbersDiffer(value, original));
}

// Codes the extractor writes into semantic fields; labels for people.
const MEASURE_LABELS = {
  doanh_thu: "Doanh thu",
  loi_nhuan: "Lợi nhuận",
  bookings: "Bookings",
  wer: "WER",
  cer: "CER",
};
const EVIDENCE_KEY = /^ev-[\w-]+$/;
const SNAKE_CODE = /^[a-z0-9]+(_[a-z0-9]+)+$/;

function readablePart(part) {
  const text = String(part ?? "").trim();
  if (!text || text === "unknown" || EVIDENCE_KEY.test(text)) return "";
  if (MEASURE_LABELS[text]) return MEASURE_LABELS[text];
  if (SNAKE_CODE.test(text)) {
    const words = text.replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  // Multi-level table headers come as "Tổng / -": drop levels without content.
  return text.split(" / ").filter((level) => /[\p{L}\p{N}]/u.test(level)).join(" / ");
}

/** A label from the API ("a · b · c") without internal keys or codes. */
export function readableLabel(label) {
  return String(label ?? "").split(" · ").map(readablePart).filter(Boolean).join(" · ");
}

/** The same parts the API joins into a label, from a Data row. */
export function evidenceLabel(evidence) {
  const table = evidence?.table_locator ?? {};
  const chart = evidence?.chart_read ?? {};
  const semantic = evidence?.semantic ?? {};
  let parts;
  if (table.row_header || table.column_header) parts = [table.row_header, table.column_header];
  else if (evidence?.chart_read) parts = [chart.category_label, chart.series_label];
  else parts = [semantic.subject, semantic.measure, semantic.period];
  return parts.map((part) => readablePart(part && typeof part === "object" ? part.label : part)).filter(Boolean).join(" · ");
}

// "missing" is the report's own "no data" mark (a "—" cell): a fact read from
// the PDF, not a number that failed to be read.
const DATA_STATUS_LABELS = {
  missing: "Không có số liệu",
  unreadable: "Chưa đọc được số",
  ambiguous: "Chưa rõ là số nào",
};

/** What the status of a number says, or "" when it is a verified number. */
export function dataStatusLabel(status) {
  if (!status || status === "valid") return "";
  return DATA_STATUS_LABELS[status] ?? "Có thể đọc sai";
}

/** True when the number was not verified and the user should check it. */
export function needsCheck(status) {
  return Boolean(status) && status !== "valid" && status !== "missing";
}

// Python's text for a Decimal, e.g. Decimal('3110'). People never see it.
const DECIMAL_REPR = /Decimal\((['"])(-?\d+(?:\.\d+)?(?:E[+-]?\d+)?)\1\)/gi;

/** Script text with every Decimal('x') written as the plain number x. */
export function withoutDecimalRepr(text) {
  return String(text ?? "").replace(DECIMAL_REPR, "$2");
}

// JSON, or a Python dict/list literal such as {'diff': Decimal('3110')}.
function parseLiteral(text) {
  try { return JSON.parse(text); } catch { /* not JSON */ }
  const json = text.replace(DECIMAL_REPR, "'$2'").replace(/'/g, '"')
    .replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false").replace(/\bNone\b/g, "null");
  try { return JSON.parse(json); } catch { return undefined; }
}

// One row per value; nested names are joined like Data labels ("a · b").
function flatten(value, name, rows) {
  const join = (part) => (name ? `${name} · ${part}` : part);
  if (Array.isArray(value)) value.forEach((item, index) => flatten(item, join(String(index + 1)), rows));
  else if (value && typeof value === "object") Object.entries(value).forEach(([key, item]) => flatten(item, join(readablePart(key) || key), rows));
  else rows.push({ name, value: formatNumber(withoutDecimalRepr(value ?? "")) });
  return rows;
}

/**
 * A script result as rows to show. The API sends plain values as text and
 * dicts/lists as JSON text, e.g. '{"diff": "2114", "percent": "49.66"}'.
 * A dict or list is always shown as rows, never as a literal.
 */
export function resultRows(result) {
  const text = withoutDecimalRepr(result).trim();
  const parsed = /^[[{]/.test(text) ? parseLiteral(String(result ?? "").trim()) : undefined;
  return flatten(parsed === undefined ? text : parsed, "", []);
}

/**
 * The rows of an executed script. The API names each row: label is the Data
 * row's label when the value is copied from that row, else the script's name.
 * Without result_rows the result text is split into rows.
 */
export function scriptResultRows(formula) {
  const rows = Array.isArray(formula?.result_rows) ? formula.result_rows : [];
  if (!rows.length) return resultRows(formula?.result);
  return rows.map((row) => ({
    name: readableLabel(row.label) || readableLabel(row.name),
    value: formatNumber(withoutDecimalRepr(row.value ?? "")),
  }));
}

/** Calculations with the same code and result are one calculation. */
export function distinctFormulas(formulas) {
  const seen = new Set();
  return (formulas ?? []).filter((formula) => {
    const key = JSON.stringify([formula.expression, formula.result]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** "smooth" unless the reader asked the system for less motion; the CSS rule cannot reach scrolls made from code. */
export const scrollBehavior = () => (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

export function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" });
}

// The unit the extractor read next to a number, in words people say: "220 tỷ đồng", "8%".
const UNIT_WORDS = {
  PERCENT: "%", VND: "đồng", VND_THOUSAND: "nghìn đồng", VND_MILLION: "triệu đồng", VND_BILLION: "tỷ đồng",
  THOUSAND: "nghìn", MILLION: "triệu", BILLION: "tỷ", USD: "USD",
  TIMES: "lần", TONNE: "tấn", THOUSAND_TONNE: "nghìn tấn",
};
export function valueWithUnit(evidence) {
  const value = evidence?.current_numeric_value;
  if (isEmpty(value)) return "";
  const unit = UNIT_WORDS[evidence?.semantic?.unit] ?? "";
  return unit === "%" ? `${formatNumber(value)}%` : unit ? `${formatNumber(value)} ${unit}` : formatNumber(value);
}
