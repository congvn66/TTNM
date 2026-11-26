// Display helpers for numbers and data labels. The API stores numbers as
// canonical decimal strings ("21350", "17.05"); users read Vietnamese style
// ("21.350", "17,05").

const DECIMAL = /^-?\d+(\.\d+)?$/;

export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "";
  const text = String(value).trim();
  if (!DECIMAL.test(text)) return text;
  const negative = text.startsWith("-");
  const [integer, fraction] = text.replace("-", "").split(".");
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

const DATA_STATUS_LABELS = {
  missing: "Chưa đọc được số",
  ambiguous: "Chưa rõ là số nào",
};

/** Why a number needs checking, or "" when it is verified. */
export function dataStatusLabel(status) {
  if (!status || status === "valid") return "";
  return DATA_STATUS_LABELS[status] ?? "Cần kiểm tra";
}

/**
 * A script result as rows to show. The API sends plain values as text and
 * dicts/lists as JSON text, e.g. '{"diff": "2114", "percent": "49.66"}'.
 */
export function resultRows(result) {
  const text = String(result ?? "").trim();
  let parsed = text;
  if (/^[[{]/.test(text)) {
    try { parsed = JSON.parse(text); } catch { parsed = text; }
  }
  const value = (item) => (item && typeof item === "object" ? JSON.stringify(item) : formatNumber(item));
  if (Array.isArray(parsed)) return parsed.map((item, index) => ({ name: String(index + 1), value: value(item) }));
  if (parsed && typeof parsed === "object") return Object.entries(parsed).map(([name, item]) => ({ name: readablePart(name) || name, value: value(item) }));
  return [{ name: "", value: formatNumber(parsed) }];
}

export function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" });
}
