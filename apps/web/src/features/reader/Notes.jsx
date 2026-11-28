import { useEffect, useState } from "react";
import { answerBlocks } from "./AnswerText.jsx";
import { differsFromReading, distinctFormulas, formatNumber as formatDecimal, readableLabel, scriptResultRows, scrollBehavior } from "./format.js";
import { readableFormula } from "./formulaView.js";
import { chipFromFormula, formatNumber, linkNumbers, readNumberCandidates, resultNumbers } from "./reportChecks.js";
import { useElapsed } from "./signals.js";
import { FormulaLine, InputTag, partColor, peekProps } from "./Calc.jsx";
import { Icon } from "./Icon.jsx";
import "./notes.css";

// How a number was read, from the reading's method label.
const CHART_READ = /nhãn|biểu đồ|trục/i;
const AXIS_ESTIMATE = /ước lượng|trục/i;
const FROM_IMAGE = /ocr/i;
const isChartValue = (item) => CHART_READ.test(item.method_label ?? "") || String(item.evidence_key ?? "").startsWith("chart");
const isUnsure = (item) => Boolean((item.data_status && item.data_status !== "valid") || AXIS_ESTIMATE.test(item.method_label ?? "") || FROM_IMAGE.test(item.method_label ?? ""));

// Codes for a busy AI service. The backend writes one of these on a rate-limited answer.
const BUSY_CODES = new Set(["AI_BUSY", "RATE_LIMITED", "AI_RATE_LIMITED", "AI_QUOTA_EXCEEDED", "AI_PROVIDER_UNAVAILABLE"]);

/**
 * What kind of failure an error is: "steps", "busy", "timeout", "server",
 * "ai", "lost", "network" or "other". The codes come from the server; the
 * texts are the older replies that carry no code.
 */
export function errorKind(error) {
  const text = String(error?.message ?? error ?? "");
  const code = String(error?.code ?? "");
  if (code === "AI_STEP_LIMIT" || /số bước|\bstep/i.test(text)) return "steps";
  if (BUSY_CODES.has(code) || error?.detail?.provider_http_status === 429 || error?.status === 429 || /HTTP 429|quota|rate.?limit|quá tải|đang bận/i.test(text)) return "busy";
  if (/TIMEOUT/.test(code) || /Không nhận được phản hồi|timed? ?out/i.test(text)) return "timeout";
  if (code === "QUESTION_LOST") return "lost";
  if (code === "SERVER_ERROR" || (error?.status ?? 0) >= 500 && !/^AI_/.test(code)) return "server";
  if (/^AI_/.test(code) || /\bAI\b|Không thể tạo câu trả lời|Không trả lời được/.test(text)) return "ai";
  if (/kết nối|mạng/i.test(text)) return "network";
  return "other";
}

const ERROR_TEXT = {
  steps: "Chưa trả lời được câu này. Thử hỏi cách khác.",
  busy: "Hệ thống đang bận. Thử lại sau một phút.",
  timeout: "Trả lời quá lâu nên đã dừng. Thử lại.",
  server: "Máy chủ gặp lỗi. Thử lại.",
  lost: "Câu hỏi chưa được lưu. Thử lại.",
  ai: "Không trả lời được. Thử lại.",
  network: "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.",
};

// Codes this client gives failures it sees itself; their text is the client's, not the server's.
const CLIENT_CODES = new Set(["SERVER_ERROR", "CLIENT_TIMEOUT", "QUESTION_LOST"]);
// Server texts that say nothing about the cause.
const VAGUE = /^(Không thể tạo câu trả lời|Đã xảy ra lỗi)/;

/** The server's own words for a failure it named with a code, or "" when it gave none worth showing. */
function serverText(error) {
  const code = String(error?.code ?? "");
  const text = String(error?.message ?? "").trim();
  return code && text && !CLIENT_CODES.has(code) && !VAGUE.test(text) ? text : "";
}

/**
 * Plain words for why a question failed: whose fault it is and what to do next.
 * A failure the server named with a code keeps the server's text, its single
 * source of user text; the rest (older replies, failed requests) get the client's.
 */
export function friendlyError(error) {
  const own = serverText(error);
  if (own) return own;
  const kind = errorKind(error);
  if (ERROR_TEXT[kind]) return ERROR_TEXT[kind];
  return String(error?.message ?? error ?? "") || "Không gửi được câu hỏi. Thử lại.";
}

/** A failed answer as an error: its code (wherever the backend put it) and its text. */
export function answerError(reply) {
  const answer = reply?.structured_answer ?? {};
  const warningCode = (answer.warnings ?? []).find((item) => /^[A-Z][A-Z0-9_]+$/.test(item) && item !== "JOB_FAILED");
  const code = reply?.error_code ?? reply?.error?.code ?? answer.error_code ?? answer.error?.code ?? warningCode ?? "";
  const status = reply?.provider_http_status ?? answer.provider_http_status ?? reply?.error?.provider_http_status;
  const message = String(reply?.body ?? answer.answer ?? "").replace(/^Không thể tạo câu trả lời:\s*/, "");
  return { message, code, detail: status ? { provider_http_status: status } : {} };
}

/** True for an answer the reader stopped ("Dừng"): not an error. */
export const wasStopped = (reply) => reply?.status === "failed" && /^Đã dừng/.test(String(reply.body ?? ""));
const FALLBACK_QUESTIONS = ["Báo cáo này nói về những chỉ tiêu nào?", "Doanh thu năm nay là bao nhiêu?", "Chỉ tiêu nào tăng mạnh nhất?"];

/** Numbers shown the Vietnamese way: 42.290 and 28,99. */
export function showNumber(value) {
  const text = String(value ?? "").trim();
  // The API stores canonical decimals ("21350", "17.05"); format those exactly.
  if (/^-?\d+(\.\d+)?$/.test(text)) return formatDecimal(text);
  const [number] = readNumberCandidates(text);
  if (number == null || /[a-zA-Z{]/.test(String(value))) return String(value ?? "");
  const percent = /%/.test(String(value)) ? "%" : "";
  return `${formatNumber(number)}${percent}`;
}

/** A number you can tap to see its cell on the page. */
export function NumberChip({ chip, text, active, onFocus }) {
  // A calculated number says so in words too: the "ƒ" is only drawn, and screen readers never hear it.
  const name = chip.computed
    ? `${text}. Số do máy tính ra${chip.label ? `, ${chip.label.charAt(0).toLowerCase()}${chip.label.slice(1)}` : ""}. Xem trên trang ${chip.page}`
    : `${text}${chip.label ? `, ${chip.label}` : ""}. Xem trên trang ${chip.page}`;
  // A calculated number looks different from one read off the page: underlined with "ƒ", not filled.
  return <button type="button" className={`rd-chip${chip.computed ? " computed" : ""}${chip.unsure ? " unsure" : ""}${active ? " active" : ""}`} aria-pressed={active} aria-label={name} title={name} onClick={() => onFocus({ ...chip, value: text })}>{text}</button>;
}

function Linked({ text, answer, activeKey, onFocus }) {
  return linkNumbers(text, answer).map((part, index) => part.chip
    ? <NumberChip key={index} chip={{ ...part.chip, label: readableLabel(part.chip.label) }} text={part.text} active={activeKey === part.chip.key} onFocus={onFocus} />
    : <span key={index}>{part.text}</span>);
}

/** One line of answer text: **bold** stays bold, numbers stay tappable. */
function Line({ text, ...rest }) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => /^\*\*[^*]+\*\*$/.test(part)
    ? <strong key={index}><Linked text={part.slice(2, -2)} {...rest} /></strong>
    : <Linked key={index} text={part} {...rest} />);
}

/** The answer as paragraphs and lists, never as raw markup. */
function AnswerSentence({ text, ...rest }) {
  return <div className="rd-answer">{answerBlocks(text).map((block, index) => {
    if (block.type === "p") return <p key={index}>{block.lines.map((line, lineIndex) => <span key={lineIndex}>{lineIndex > 0 && <br />}<Line text={line} {...rest} /></span>)}</p>;
    const List = block.type;
    return <List key={index}>{block.lines.map((line, lineIndex) => <li key={lineIndex}><Line text={line} {...rest} /></li>)}</List>;
  })}</div>;
}

/**
 * The answer's calculations, without the ones that only copy one cell
 * (result = value(cell)): those are lookups, and calling them a calculation
 * would mislead.
 */
export function realFormulas(answer) {
  return distinctFormulas((answer?.formulas ?? []).filter((formula) => {
    if (formula.result == null) return false;
    const inputs = formula.inputs ?? [];
    if (inputs.length !== 1 || (formula.manual_numbers ?? []).length) return true;
    const results = resultNumbers(formula.result);
    return !results.length || results.some((value) => Math.abs(value - Number(inputs[0].value)) > 1e-9);
  }));
}

/**
 * A short line when the answer's numbers need a second look, or come from a
 * chart; null when they come straight from the report's text or tables.
 */
export function confidenceOf(answer) {
  const data = (answer?.evidence ?? []).filter((item) => item.kind === "data");
  const quotes = (answer?.evidence ?? []).filter((item) => item.kind === "text");
  const formulas = realFormulas(answer);
  const typed = formulas.flatMap((formula) => formula.manual_numbers ?? []);
  if (answer?.not_found) return { kind: "warn", text: "Không tìm thấy số này trong báo cáo." };
  if (typed.length) return { kind: "warn", text: `Có số không có trong báo cáo: ${typed.map(showNumber).join(", ")}` };
  const chart = data.filter(isChartValue);
  const chartUnsure = chart.filter(isUnsure);
  if (chartUnsure.length) return { kind: "warn", text: `${chartUnsure.length} số ước lượng từ biểu đồ, có thể sai` };
  const unsure = data.filter(isUnsure);
  if (unsure.length) return { kind: "warn", text: `${unsure.length} số đọc từ ảnh, có thể sai` };
  if (chart.length) {
    const pages = [...new Set(chart.map((item) => item.page).filter(Boolean))];
    return { kind: "neutral", text: `Số đọc từ nhãn trên biểu đồ${pages.length ? `, trang ${pages.join(", ")}` : ""}` };
  }
  if (formulas.length || data.length) return null;
  // Only quotes, no number to check: point at the pages they come from.
  const pages = [...new Set(quotes.map((item) => item.page).filter(Boolean))];
  if (pages.length) return { kind: "warn", text: `Xem trang ${pages.join(", ")}` };
  return null;
}

function sourceRows(answer) {
  return (answer?.evidence ?? []).filter((item) => item.kind === "data" && item.page).map((item) => ({
    key: item.evidence_key ?? `${item.page}-${item.value}`,
    page: item.page,
    boxes: item.bbox ? [item.bbox] : [],
    label: readableLabel(item.label),
    value: showNumber(item.value ?? item.raw_text),
    raw: item.raw_text || "",
    unsure: isUnsure(item),
  }));
}

/**
 * What the answer's own numbers are now, against the values it was made
 * from. `evidences` are the report's current numbers; without them nothing
 * is known and every field is null.
 */
export function inputState(answer, evidences) {
  if (!answer || !evidences?.length) return { changed: null, edited: [] };
  const now = new Map(evidences.map((item) => [item.evidence_key, item]));
  const used = [
    ...(answer.evidence ?? []).filter((item) => item.kind === "data" && item.evidence_key).map((item) => ({ key: item.evidence_key, value: item.value })),
    ...(answer.formulas ?? []).flatMap((formula) => (formula.inputs ?? []).map((input) => ({ key: input.evidence_key, value: input.value }))),
  ].filter((item) => item.key && item.value != null && item.value !== "");
  if (!used.length) return { changed: null, edited: [] };
  const same = (a, b) => b != null && Math.abs(Number(a) - Number(b)) <= Math.max(1e-9, Math.abs(Number(b)) * 1e-12);
  const changed = used.some((item) => !now.has(item.key) || !same(item.value, now.get(item.key).current_numeric_value));
  // Numbers the reader corrected that this answer already uses: the PDF still prints the old one.
  const seen = new Set();
  const edited = used.flatMap((item) => {
    const cell = now.get(item.key);
    if (!cell || seen.has(item.key) || !same(item.value, cell.current_numeric_value) || !differsFromReading(cell.current_numeric_value, cell.original_numeric_value)) return [];
    seen.add(item.key);
    return [{ key: item.key, value: formatNumber(Number(cell.current_numeric_value)), printed: cell.original_numeric_value != null ? formatNumber(Number(cell.original_numeric_value)) : (cell.raw_text ?? "") }];
  });
  return { changed, edited };
}

/** A quote that is only a table row ("Tổng 42.290 49.880 — 14.525") repeats the rows listed above it. */
function rowLikeQuote(text) {
  const numbers = String(text ?? "").match(/\d[\d.,]*/g) ?? [];
  const words = String(text ?? "").replace(/[-−–—(]?\d[\d.,]*%?\)?/g, " ").split(/\s+/).filter((word) => /\p{L}/u.test(word));
  return numbers.length >= 2 && words.length <= 3;
}

/** The answer as it reads after a swap: the swapped cells in its sources and the swapped calculation. */
export function swappedAnswer(answer, swap) {
  if (!answer || !swap?.formula) return answer;
  const inputs = new Map((swap.formula.inputs ?? []).map((input) => [input.evidence_key, input]));
  const evidence = (answer.evidence ?? []).flatMap((item) => {
    if (item.kind !== "data" || !swap.swap?.[item.evidence_key]) return [item];
    const input = inputs.get(swap.swap[item.evidence_key]);
    return input ? [{ kind: "data", page: input.page, bbox: input.bbox, evidence_key: input.evidence_key, label: input.label, value: input.value, data_status: "valid" }] : [];
  });
  return { ...answer, evidence, formulas: (answer.formulas ?? []).map((formula, index) => (index === swap.formulaIndex ? swap.formula : formula)) };
}

// Names a calculation script gives its results, in words people use.
const RESULT_NAMES = [
  [/^(diff|difference|delta|chenh_?lech|change)$/i, "Chênh lệch"],
  [/^(pct|percent|percentage|pct_change|growth|tang_truong|ty_le_tang)$/i, "Tỷ lệ thay đổi", "%"],
  [/^(ratio|ty_le|rate|share|margin|bien)$/i, "Tỷ lệ"],
  [/^(total|sum|tong)$/i, "Tổng"],
  [/^(avg|mean|average|trung_binh)$/i, "Trung bình"],
  [/^(max|highest|cao_nhat)$/i, "Cao nhất"],
  [/^(min|lowest|thap_nhat)$/i, "Thấp nhất"],
  [/^(result|ket_qua|value|answer)$/i, "Kết quả"],
];
function resultName(name) {
  const raw = String(name ?? "").trim();
  const hit = RESULT_NAMES.find(([pattern]) => pattern.test(raw.replace(/\s+/g, "_")));
  return hit ? { name: hit[1], unit: hit[2] ?? "", known: true } : { name: raw, unit: "", known: false };
}

// What a plain formula computes, from its shape (C is a cell): "C − C" is a difference.
const FORMULA_NAMES = [
  [/^C−C$/, "Chênh lệch"],
  [/^C(\+C)+$/, "Tổng"],
  [/^\(C−C\)÷C×100$/, "Tỷ lệ thay đổi"],
  [/^C÷C(×100)?$/, "Tỷ lệ"],
];

/** The name of a result whose script gives it no known name, read from its formula; "" when it is not a plain shape. */
export function formulaName(formula, target = null) {
  const pieces = formula?.expression ? readableFormula(formula.expression, target) : null;
  if (!pieces) return "";
  const shape = pieces.map((piece) => (piece.cell ? "C" : piece.text)).join("").replace(/\s+/g, "");
  return FORMULA_NAMES.find(([pattern]) => pattern.test(shape))?.[1] ?? "";
}

/** Each result of a calculation, as "49.880 − 42.290 = 7.590" when the script is plain arithmetic. */
function ResultValue({ formula }) {
  const rows = scriptResultRows(formula);
  const raw = formula.result_rows?.length === rows.length ? formula.result_rows : null;
  if (rows.length === 1 && !rows[0].name) {
    return <p className="rd-result-line"><FormulaLine formula={formula} result={raw?.[0]?.name ?? null} lead="" /><b>= {rows[0].value}</b></p>;
  }
  return <ul className="rd-result">{rows.map((row, index) => {
    const { name, unit } = resultName(row.name);
    return <li key={index}><span>{name}</span><span className="rd-result-line"><FormulaLine formula={formula} result={raw?.[index]?.name ?? null} lead="" /><b>{raw ? "= " : ""}{row.value}{unit && !String(row.value).includes(unit) ? unit : ""}</b></span></li>;
  })}</ul>;
}

/** Where an answer's numbers and quotes come from, and how it calculated. */
function SourcesDetails({ answer, id, activeKey, onFocus, scanned, edited = [], label = "Nguồn" }) {
  const rows = sourceRows(answer);
  // A quote that is only a table row adds nothing to the rows listed above it.
  const quotes = (answer?.evidence ?? []).filter((item) => item.kind === "text" && item.quote && !(rowLikeQuote(item.quote) && rows.some((row) => row.page === item.page)));
  const formulas = realFormulas(answer);
  const pages = [...new Set([...rows, ...quotes].map((item) => item.page).filter(Boolean))];
  if (!rows.length && !quotes.length && !formulas.length) return null;
  // The PDF still prints a number the reader corrected: say so next to the quote that shows it.
  const correctedIn = (quote) => edited.filter((item) => item.printed && quote.includes(item.printed));
  return <details className="rd-sources" onToggle={(event) => { if (event.currentTarget.open) { const node = event.currentTarget; window.requestAnimationFrame(() => node.scrollIntoView({ block: "nearest", behavior: scrollBehavior() })); } }}>
    <summary>{label}{pages.length ? ` · tr. ${pages.join(", ")}` : ""}</summary>
    {rows.length > 0 && <ul className="rd-source-list">{rows.map((row) => <li key={row.key}><button type="button" className={activeKey === row.key ? "active" : ""} onClick={() => onFocus(row)}><span>Trang {row.page} · {row.label || "số trong bảng"}</span><b>{row.value}</b></button></li>)}</ul>}
    {quotes.map((quote, index) => <button type="button" key={index} className="rd-quote" onClick={() => onFocus({ page: quote.page, boxes: quote.bbox ? [quote.bbox] : [], quote: quote.quote, label: `Đoạn văn ở trang ${quote.page}`, key: `quote-${id}-${index}` })}>“{quote.quote}”
      <small>Trang {quote.page}{scanned ? " · bản scan" : ""}{correctedIn(quote.quote).map((item) => ` · ${item.printed} đã sửa thành ${item.value}`).join("")}</small></button>)}
    {formulas.map((formula, index) => <div key={index} className="rd-formula"><span>Cách tính</span>{formula.substitution && <p>{formula.substitution}</p>}<ResultValue formula={formula} /></div>)}
  </details>;
}

/**
 * The one number an answer is about, shown large above the sentence, so the
 * reader sees the result first and can tap it to see the cell. Only when the
 * answer rests on a single cell or a single calculated value.
 */
/** True when the sentence writes this number as a percentage, at any rounding ("42,8" matches "42,80%" and "42,8 %"). */
function sentenceHasPercent(sentence, value) {
  const targets = readNumberCandidates(value);
  return (String(sentence ?? "").match(/-?\d[\d.,]*\s?%/g) ?? []).some((token) => {
    const decimals = token.match(/[.,](\d{1,2})\s?%$/)?.[1].length ?? 0;
    return readNumberCandidates(token).some((written) => targets.some((target) => Math.abs(written - target) <= 0.5 * 10 ** -decimals + 1e-9));
  });
}

/** Which of a script's results the sentence is about: the one it writes as a %, else the first it writes at all. */
/** How many of the rows' values the sentence writes. */
function statedCount(sentence, rows) {
  const written = (String(sentence ?? "").match(/-?\d+(?:[.,]\d+)*/g) ?? []).flatMap(readNumberCandidates);
  return rows.filter((row) => readNumberCandidates(String(row.value)).some((value) => written.some((number) => Math.abs(number - value) <= Math.max(0.005, Math.abs(value) * 1e-6)))).length;
}

function headlineRow(sentence, rows) {
  // A number ends at its last digit: "24.050." at the end of a sentence is 24.050.
  const written = (String(sentence ?? "").match(/-?\d+(?:[.,]\d+)*/g) ?? []).flatMap(readNumberCandidates);
  const appears = (row) => readNumberCandidates(String(row.value)).some((value) => written.some((number) => Math.abs(number - value) <= Math.max(0.005, Math.abs(value) * 1e-6)));
  // Among results the sentence writes as a %, one named like a percentage first, then the closest:
  // in "3 chi nhánh, chiếm 3%" the 3% is the share (3,2), not the count (3).
  const percents = (String(sentence ?? "").match(/-?\d+(?:[.,]\d+)*\s?%/g) ?? []).flatMap(readNumberCandidates);
  const gap = (row) => Math.min(...readNumberCandidates(String(row.value)).flatMap((value) => percents.map((written) => Math.abs(written - value))));
  const named = (row) => (/pct|percent|ty_?le|tỷ lệ|growth|tang_truong|share|chiem|margin|bien/i.test(row.name ?? "") ? 0 : 1);
  const percent = rows.map((row, index) => ({ index, named: named(row), gap: sentenceHasPercent(sentence, row.value) ? gap(row) : Infinity }))
    .filter((item) => Number.isFinite(item.gap))
    .sort((a, b) => a.named - b.named || a.gap - b.gap)[0];
  return percent ? percent.index : rows.findIndex(appears);
}

/**
 * The cells behind one result of a script, keeping each one's number in the
 * whole calculation (a script can read 6 cells and use 2 for this result).
 */
function resultInputs(formula, row) {
  const keys = row?.source_keys;
  return (formula.inputs ?? []).map((input, index) => ({ ...input, index })).filter((input) => !keys?.length || keys.includes(input.evidence_key));
}

/** The chip of one result: only its own cells light up on the page. */
function resultChip(formula, inputs) {
  // The page to show is the page of this result's own cells, not of the script's first cell.
  const chip = chipFromFormula({ ...formula, inputs });
  if (!chip) return null;
  const indexOf = new Map(inputs.map((input) => [input.evidence_key, input.index]));
  return { ...chip, formula, parts: chip.parts.map((part) => ({ ...part, index: indexOf.get(part.key) ?? part.index })) };
}

/** The choices of a clarifying question: tools-mode `options`, or the older clarification card's points. */
export function clarifyOptions(answer) {
  if (!answer) return [];
  if (Array.isArray(answer.options) && answer.options.length) return answer.options.filter((item) => typeof item === "string" && item.trim());
  if (answer.presentation === "clarification_v1") return (answer.sections?.[0]?.points ?? []).filter((item) => typeof item === "string" && item.trim());
  return [];
}

export function headlineOf(answer) {
  if (!answer || answer.not_found) return null;
  const rows = sourceRows(answer);
  const formulas = realFormulas(answer);
  if (formulas.length === 1) {
    const formula = formulas[0];
    const results = scriptResultRows(formula);
    if (!chipFromFormula(formula) || !results.length) return null;
    // A script may give several results ({diff, pct}); the headline is the one the sentence states.
    // A sentence that lists three or more of them (one per month, one per region) has no single answer.
    if (results.length >= 3 && formula.result_rows?.length === results.length && statedCount(answer.answer, formula.result_rows) >= 3) return null;
    const at = results.length === 1 ? 0 : (formula.result_rows?.length === results.length ? headlineRow(answer.answer, formula.result_rows) : -1);
    if (at < 0) return null;
    const row = formula.result_rows?.[at];
    const result = row?.name ?? null;
    const inputs = resultInputs(formula, row);
    const chip = resultChip(formula, inputs);
    if (!chip?.parts.length) return null;
    const { name, unit, known } = resultName(results[at].name);
    let value = `${results[at].value}${unit && !String(results[at].value).includes(unit) ? unit : ""}`;
    // The script returns a bare number; the sentence says whether it is a percentage.
    if (!value.includes("%") && sentenceHasPercent(answer.answer, formula.result_rows?.[at]?.value ?? results[at].value)) value += "%";
    // Only a known name ("Tỷ lệ thay đổi"); a script's own variable name ("sum_q1") means nothing to the reader.
    // A name the script does not give comes from the formula's shape (a − b is a difference).
    const label = known && name !== "Kết quả" ? name : formulaName(formula, result);
    return { value, label, parts: chip.parts, inputs, chip: { ...chip, value, result }, formula, result };
  }
  if (formulas.length || rows.length !== 1 || !rows[0].value || rows[0].value === "—") return null;
  return { value: rows[0].value, label: rows[0].label || `Số ở trang ${rows[0].page}`, chip: rows[0] };
}

/** The headline after the reader swapped cells: the same result of the same script, run on the chosen cells. */
export function swappedHeadline(headline, formula) {
  const rows = scriptResultRows(formula);
  const at = Math.max(0, (formula.result_rows ?? []).findIndex((row) => row.name === headline.result));
  const inputs = resultInputs(formula, formula.result_rows?.[at]);
  const chip = resultChip(formula, inputs);
  if (!rows[at] || !chip) return headline;
  const value = `${rows[at].value}${headline.value.endsWith("%") && !String(rows[at].value).includes("%") ? "%" : ""}`;
  return { ...headline, value, parts: chip.parts, inputs, chip: { ...chip, value, result: headline.result, key: `${chip.key}-swapped` }, formula, original: headline.value };
}

/**
 * The answer's number, large, and under it each input of its calculation with
 * its numbered tag: tap one to see its cell, hover or focus it to outline the
 * cell, "Chọn ô khác" when the AI read the wrong cell.
 */
function Headline({ headline, active, activeKey, onFocus, onPeek, onPick, busy, doubtful }) {
  const inputs = headline.inputs ?? [];
  const many = inputs.length > 1;
  return <div className={`rd-headline${headline.chip.unsure || doubtful ? " unsure" : ""}${active ? " active" : ""}${headline.original ? " changed" : ""}`}>
    <button type="button" className="rd-headline-value" aria-pressed={active} onClick={() => onFocus(headline.chip)}>
      <b>{doubtful && <i className="rd-mark unsure" aria-hidden="true">?</i>}{headline.value}{doubtful && <span className="rd-sr">, có thể không có nghĩa</span>}</b>
      {/* Words, not only a dashed outline: a swapped result must never read as the AI's answer. */}
      <span>{[headline.original && "Đã đổi ô", headline.label, `trang ${headline.chip.page}`].filter(Boolean).join(" · ")}</span>
    </button>
    {many && <ul className="rd-inputs">{inputs.map(({ index, ...input }) => {
      const chip = { page: input.page, boxes: input.bbox ? [input.bbox] : [], label: readableLabel(input.label), value: formatNumber(Number(input.value)), key: input.evidence_key };
      // Keyed by the input's place, so a swap keeps the same row and its "Đổi ô" can take focus back.
      return <li key={index} style={{ "--part": partColor(index) }}>
        <button type="button" className={`rd-calc-input${activeKey === chip.key ? " active" : ""}`} aria-pressed={activeKey === chip.key} onClick={() => onFocus(chip)} {...peekProps(input.evidence_key, onPeek)}>
          <InputTag index={index} /><b>{chip.value}</b><small>{chip.label || `trang ${input.page}`}</small>
        </button>
        {onPick && <button type="button" className="rd-button small" aria-disabled={busy || undefined} onClick={() => { if (!busy) onPick(index); }} title={busy ? "Đang tính lại…" : undefined} aria-label={`Chọn ô khác cho số ${index + 1}`}>Chọn ô khác</button>}
      </li>;
    })}</ul>}
  </div>;
}

const LATE_SECONDS = 45;

function WorkingReply({ reply, onStop }) {
  const since = Date.parse(reply.created_at ?? "") || null;
  const seconds = useElapsed(since);
  const [stopping, setStopping] = useState(false);
  return <div className="rd-waiting"><span className="rd-spinner" aria-hidden="true" /><div><b>Đang trả lời…</b>{since && seconds >= LATE_SECONDS && <small>Lâu hơn bình thường</small>}</div>
    {onStop && <button type="button" className="rd-button" disabled={stopping} onClick={async () => { setStopping(true); try { await onStop(reply); } finally { setStopping(false); } }}>{stopping ? "Đang dừng…" : "Dừng"}</button>}
  </div>;
}

/** Put text on the clipboard; the older copy command when the browser refuses the clipboard API. */
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* refused: try the older way */ }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const done = document.execCommand("copy");
    area.remove();
    return done;
  } catch { return false; }
}

/** The answer as plain text with where it comes from, for pasting elsewhere. */
export function copyableAnswer(text, pages) {
  const plain = String(text ?? "").replace(/\*\*/g, "").trim();
  const source = pages.length ? `Nguồn: trang ${pages.join(", ")}` : "";
  return [plain, source].filter(Boolean).join("\n");
}

export function AnswerCard({ note, activeKey, onFocus, onAsk, onEdit, onStop, scanned, onPeek, onPick, pickBusy = false, swap, onUndoSwap, evidences = null }) {
  const { question, reply } = note;
  // Hooks before any early return: a reply goes from "working" to done in the same card.
  const [copied, setCopied] = useState("");
  if (reply && (reply.status === "processing" || reply.structured_answer?.presentation === "processing_v1")) {
    return <article className="rd-card rd-qa waiting" aria-live="polite">{question && <p className="rd-question">{question.body}</p>}<WorkingReply reply={reply} onStop={onStop} /></article>;
  }
  const answer = reply?.structured_answer && reply.structured_answer.presentation !== "processing_v1" ? reply.structured_answer : null;
  const text = answer?.answer ?? reply?.body ?? "";
  const failed = reply && reply.status === "failed";
  const stopped = wasStopped(reply);
  const confidence = confidenceOf(answer);
  const original = failed ? null : headlineOf(answer);
  const headline = original && swap ? swappedHeadline(original, swap.formula) : original;
  // After a swap the sources and the calculation are the swapped ones; the AI's sentence is about the original cells.
  const shown = swap && original ? swappedAnswer(answer, swap) : answer;
  // Only a calculation can be run again on other cells; its place in the stored list names it to the server.
  const formulaIndex = original?.formula ? (answer.formulas ?? []).indexOf(original.formula) : -1;
  const rows = sourceRows(shown);
  const quotes = (shown?.evidence ?? []).filter((item) => item.kind === "text" && item.quote);
  const pages = [...new Set([...rows, ...quotes].map((item) => item.page).filter(Boolean))];
  const inputs = inputState(answer, evidences);
  // The server marks an answer when a number it used was edited; putting the number back clears the mark here.
  const needsUpdate = Boolean(reply?.needs_update) && inputs.changed !== false;
  const copy = async () => {
    const done = await copyText(copyableAnswer(text, pages));
    setCopied(done ? "Đã chép" : "Không chép được");
    window.setTimeout(() => setCopied(""), 1800);
  };
  const sentence = <AnswerSentence text={text} answer={answer} activeKey={activeKey} onFocus={onFocus} />;

  return <article id={`note-${note.id}`} tabIndex={-1} className={`rd-card rd-qa${failed ? (stopped ? " stopped" : " failed") : ""}`}>
    {question && <p className="rd-question">{question.body}</p>}
    {failed && <>{stopped ? <p className="rd-stopped-text">Đã dừng</p> : <p className="rd-error-text">{friendlyError(answerError(reply))}</p>}<button type="button" className="rd-button" onClick={() => onAsk(question?.body ?? "")}>Hỏi lại</button></>}
    {!failed && reply && <>
      {headline && <Headline headline={headline} active={activeKey === headline.chip.key} activeKey={activeKey} onFocus={onFocus} onPeek={onPeek} busy={pickBusy} doubtful={Boolean(swap?.warning)}
        onPick={onPick && formulaIndex >= 0 && !needsUpdate ? (index) => onPick({ note, base: original, headline, formulaIndex, index }) : null} />}
      {swap && original && <p className="rd-fyi changed">Đã đổi ô · gốc {original.value} {!pickBusy && <button type="button" className="rd-link" onClick={() => onUndoSwap(note.id)}>Hoàn tác</button>}</p>}
      {swap?.warning && <p className="rd-fyi warn"><i className="rd-mark unsure" aria-hidden="true">?</i><span>{swap.warning}</span></p>}
      {swap && original ? <details className="rd-orig"><summary>Câu trả lời với ô gốc</summary>{sentence}</details> : sentence}
      {confidence && <p className={`rd-confidence ${confidence.kind}`}><i aria-hidden="true" />{confidence.text}</p>}
      {inputs.edited.length > 0 && !needsUpdate && <p className="rd-confidence neutral"><i aria-hidden="true" />{inputs.edited.length === 1 ? `Dùng số đã sửa: ${inputs.edited[0].value}, PDF ghi ${inputs.edited[0].printed}` : `Dùng ${inputs.edited.length} số đã sửa`}</p>}
      {needsUpdate && <p className="rd-confidence neutral"><i aria-hidden="true" />Số liệu đã thay đổi{question && <> · <button type="button" className="rd-link" onClick={() => onAsk(question.body)}>Hỏi lại</button></>}</p>}
      {clarifyOptions(answer).length > 0 && <div className="rd-next" role="group" aria-label="Chọn một ý">
        {clarifyOptions(answer).map((option) => <button key={option} type="button" onClick={() => onAsk(option)}>{option}</button>)}
      </div>}
      {(answer?.warnings ?? []).map((warning) => <p key={warning} className="rd-fyi warn"><i className="rd-mark unsure" aria-hidden="true">!</i><span>{warning}</span></p>)}
      {answer?.not_found && <div className="rd-next">
        {pages.map((page) => <button key={page} type="button" onClick={() => onFocus({ page, boxes: [], label: `Trang ${page}`, key: `page-${note.id}-${page}` })}>Mở trang {page}</button>)}
        {question && <button type="button" onClick={() => onEdit(question.body)}>Sửa câu hỏi</button>}
      </div>}
      <SourcesDetails answer={shown} id={note.id} activeKey={activeKey} onFocus={onFocus} scanned={scanned} edited={inputs.edited} />
      <div className="rd-actions">
        {question && !answer?.not_found && <button type="button" onClick={() => onEdit(question.body)} aria-label="Sửa câu hỏi" title="Sửa câu hỏi"><Icon name="pencil" size={15} /></button>}
        <button type="button" onClick={copy} aria-label={copied || "Sao chép"} title={copied || "Sao chép"}><Icon name="copy" size={15} />{copied && <span role="status">{copied}</span>}</button>
      </div>
    </>}
  </article>;
}

/** A question the client is still sending, or one that never reached the server. */
export function PendingCard({ item, onRetry, onDismiss, onStop }) {
  const waiting = item.status === "asking" || item.status === "sent";
  const seconds = useElapsed(waiting ? item.startedAt : null);
  const stop = onStop ? () => onStop(item.id) : item.stop;
  const className = item.status === "failed" ? " failed" : item.status === "stopped" ? " stopped" : " waiting";
  return <article className={`rd-card rd-qa${className}`} aria-live="polite">
    <p className="rd-question">{item.question}</p>
    {waiting && <div className="rd-waiting"><span className="rd-spinner" aria-hidden="true" /><div><b>Đang trả lời…</b>{seconds >= LATE_SECONDS && <small>Lâu hơn bình thường</small>}</div>
      {stop && <button type="button" className="rd-button" onClick={stop}>Dừng</button>}</div>}
    {item.status === "stopped" && <><p className="rd-stopped-text">Đã dừng</p><div className="rd-actions"><button type="button" className="rd-button" onClick={() => onRetry(item)}>Hỏi lại</button><button type="button" onClick={() => onDismiss(item.id)}>Bỏ qua</button></div></>}
    {item.status === "failed" && <><p className="rd-error-text">{friendlyError(item.errorObject ?? item.error)}</p><div className="rd-actions"><button type="button" className="rd-button" onClick={() => onRetry(item)}>Thử lại</button><button type="button" onClick={() => onDismiss(item.id)}>Bỏ qua</button></div></>}
  </article>;
}

const SECONDS_PER_PAGE = 12;
// When this browser first saw a report being read: the server gives no start time.
const readingSince = new Map();

/** When reading started: the server's time if it gives one, else when this page first saw it. */
function useReadingStart(report) {
  const id = report?.id;
  const status = report?.extraction_status;
  const given = Date.parse(report?.extraction_started_at ?? report?.started_at ?? "") || null;
  const [seen, setSeen] = useState(() => readingSince.get(id) ?? null);
  useEffect(() => {
    if (status === "processing" && id && !readingSince.has(id)) readingSince.set(id, Date.now());
    setSeen(readingSince.get(id) ?? null);
  }, [id, status]);
  return given ?? (status === "processing" ? seen ?? Date.now() : null);
}

/**
 * Progress of a new report. `uploading` is the moment before the server has
 * the file. A report waiting for a free worker says so, with no moving bar:
 * the bar starts when reading starts.
 */
export function ReadingCard({ report, uploading = false }) {
  const queued = !uploading && report?.extraction_status === "queued";
  const since = useReadingStart(report);
  const seconds = useElapsed(uploading || queued ? null : since);
  const estimate = Math.max(15, (report?.page_count ?? 3) * SECONDS_PER_PAGE);
  const percent = Math.min(95, Math.round((seconds / estimate) * 100));
  const late = seconds > estimate * 1.5;
  const title = uploading ? `Đang tải lên ${report.file_name}…` : queued ? "Đang chờ đọc…" : "Đang đọc báo cáo…";
  return <article className="rd-card rd-reading" aria-live="polite">
    <header><span className="rd-spinner large" aria-hidden="true" /><div><h3>{title}</h3></div></header>
    {!uploading && !queued && <div className="rd-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Tiến độ"><span style={{ width: `${percent}%` }} /></div>}
    {late && !uploading && !queued && <p className="rd-hint">Lâu hơn bình thường</p>}
  </article>;
}

export function FailedCard({ report, onRetry, busy }) {
  // A reading that ended without a result (a lost job) is not a file the app cannot read.
  const stopped = report?.extraction_error === "EXTRACTION_STOPPED";
  return <article className="rd-card rd-failed" role="alert">
    <h3>{stopped ? "Chưa đọc xong báo cáo này" : "Không đọc được báo cáo này"}</h3>
    {onRetry && <button type="button" className="rd-button" onClick={() => onRetry(report)} disabled={busy}>{stopped ? "Thử lại" : "Đọc lại"}</button>}
  </article>;
}

function CheckLine({ check, activeKey, onFocus, onDismiss }) {
  const chip = <NumberChip chip={check.chip} text={formatNumber(check.total)} active={activeKey === check.chip.key} onFocus={onFocus} />;
  const rounding = check.ok && Math.abs(check.diff) > 1e-9;
  // A column the reading found no header for is named by its page.
  const column = String(check.column ?? "").trim() || `Cột ở trang ${check.chip.page}`;
  if (rounding) return <li className="ok"><span aria-hidden="true">✓</span><p>{column}: tổng {formatNumber(check.sum)}, ghi {chip}, lệch {formatNumber(Math.abs(check.diff))}</p></li>;
  return check.ok
    ? <li className="ok"><span aria-hidden="true">✓</span><p>{column}: khớp</p></li>
    : <li className="bad"><span aria-hidden="true">!</span><p>{column}: tổng {formatNumber(check.sum)}, ghi {chip}, lệch {formatNumber(Math.abs(check.diff))}
      {onDismiss && <button type="button" className="rd-link rd-dismiss" onClick={() => onDismiss(check)} aria-label={`Bỏ qua: ${column}`}>Bỏ qua</button>}</p></li>;
}

const BRIEF_REASONS = {
  busy: "Hệ thống đang bận, thử lại sau một phút.",
  timeout: "Tóm tắt lâu quá nên đã dừng.",
  steps: "Tóm tắt lâu quá nên đã dừng.",
  server: "Máy chủ gặp lỗi.",
  network: "Không kết nối được máy chủ.",
};

/** A failed overview, with its reason when the reason tells the reader what to do. */
export function briefError(error) {
  const own = serverText(error);
  const kind = errorKind(error);
  // The server's own words about the overview ("Tóm tắt mất quá lâu. Thử lại sau.") stand alone.
  if (own && /^BRIEF_/.test(String(error.code))) return own;
  if (own && (kind === "busy" || kind === "timeout")) return `Chưa tóm tắt được. ${own}`;
  const reason = BRIEF_REASONS[kind];
  return reason ? `Chưa tóm tắt được. ${reason}` : "Chưa tóm tắt được";
}

/** The overview's own text: the caution line goes in its own box. */
function splitCaution(text) {
  const lines = String(text ?? "").split(/\r?\n/);
  const caution = lines.filter((line) => /^\s*[-*•]?\s*\**cần chú ý\**\s*:/i.test(line)).map((line) => line.replace(/^\s*[-*•]?\s*\**cần chú ý\**\s*:\s*/i, ""));
  const main = lines.filter((line) => !/^\s*[-*•]?\s*\**cần chú ý\**\s*:/i.test(line)).join("\n");
  return { main, caution };
}

function firstSentence(text) {
  const plain = String(text ?? "").replace(/\*\*/g, "").split(/\r?\n/).find((line) => line.trim()) ?? "";
  return plain.length > 140 ? `${plain.slice(0, 137)}…` : plain;
}

/**
 * The report overview: what the report is, its key points with numbers you
 * can tap, what it warns about, and what SourceLens checked on its own.
 */
export function BriefCard({ brief, briefing, dismissed = new Set(), onDismiss, onRestore, activeKey, onFocus, onAsk, onRetry, onOpenData, asked, collapsed, scanned }) {
  const [open, setOpen] = useState(!collapsed);
  useEffect(() => { if (collapsed) setOpen(false); }, [collapsed]);
  const answer = brief?.status === "ready" ? brief.answer : null;
  const { main, caution } = splitCaution(answer?.answer);
  const bad = briefing?.checks.filter((check) => !check.ok && !dismissed.has(check.chip.key)) ?? [];
  const skipped = briefing?.checks.filter((check) => !check.ok && dismissed.has(check.chip.key)).length ?? 0;
  const good = briefing?.checks.filter((check) => check.ok) ?? [];
  const questions = (briefing?.suggestions?.length ? briefing.suggestions : FALLBACK_QUESTIONS).filter((question) => !asked?.has(question.trim()));
  return <article className={`rd-card rd-brief${open ? "" : " folded"}`}>
    <button type="button" className="rd-fold" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <span className="rd-kicker">Tóm tắt</span>
      {!open && bad.length > 0 && <span className="rd-fold-status bad">{bad.length} chỗ không khớp</span>}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d={open ? "m6 15 6-6 6 6" : "m6 9 6 6 6-6"} /></svg>
    </button>
    {!open && answer && <p className="rd-brief-teaser">{firstSentence(main)}</p>}
    {open && <>
      {brief?.status === "loading" && <div className="rd-brief-loading" aria-live="polite"><span className="rd-spinner" aria-hidden="true" /><div><b>Đang tóm tắt…</b></div></div>}
      {brief?.status === "loading" && <div className="rd-skeleton-lines" aria-hidden="true"><i /><i /><i /></div>}
      {brief?.status === "error" && <div className="rd-brief-error"><p className="rd-error-text">{briefError(brief.error)}</p><button type="button" className="rd-button" onClick={onRetry}>Thử lại</button></div>}
      {answer && <>
        <AnswerSentence text={main} answer={answer} activeKey={activeKey} onFocus={onFocus} />
        {caution.length > 0 && <div className="rd-caution"><strong>Cần chú ý</strong>{caution.map((line, index) => <p key={index}><Line text={line} answer={answer} activeKey={activeKey} onFocus={onFocus} /></p>)}</div>}
        <SourcesDetails answer={answer} id="brief" activeKey={activeKey} onFocus={onFocus} scanned={scanned} />
      </>}
      {scanned && <p className="rd-banner">Bản scan, số có thể bị đọc sai</p>}
      {bad.length > 0 && <div className="rd-alert"><strong>Tổng không khớp</strong><ul className="rd-checks">{bad.map((check) => <CheckLine key={check.chip.key} check={check} activeKey={activeKey} onFocus={onFocus} onDismiss={onDismiss} />)}</ul></div>}
      {skipped > 0 && <p className="rd-skipped">Đã ẩn {skipped} · <button type="button" className="rd-link" onClick={onRestore}>Hiện lại</button></p>}
      {!bad.length && !skipped && good.length > 0 && <p className="rd-verified"><span aria-hidden="true">✓</span>{good.length} dòng tổng khớp</p>}
      {questions.length > 0 && <div className="rd-suggest"><span>Gợi ý</span>{questions.map((question) => <button type="button" key={question} onClick={() => onAsk(question)}>{question}</button>)}</div>}
      <button type="button" className="rd-link rd-brief-data" onClick={onOpenData}>Số liệu</button>
    </>}
  </article>;
}
