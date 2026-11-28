import { useEffect, useState } from "react";
import { answerBlocks } from "./AnswerText.jsx";
import { distinctFormulas, formatNumber as formatDecimal, readableLabel, scriptResultRows, scrollBehavior, withoutDecimalRepr } from "./format.js";
import { chipFromFormula, formatNumber, linkNumbers, readNumberCandidates, resultNumbers } from "./reportChecks.js";
import { useElapsed } from "./signals.js";
import { InputTag, partColor, peekProps } from "./Calc.jsx";

const ESTIMATED = /biểu đồ|ước lượng|trục|ocr/i;

/** Plain words for why a question failed: whose fault it is and what to do next. */
export function friendlyError(error) {
  const text = String(error?.message ?? error ?? "");
  const code = error?.code ?? "";
  if (/số bước|step/i.test(text) || code === "AI_STEP_LIMIT") return "Câu này mình chưa làm xong trong một lượt. Thử hỏi ngắn hơn, ví dụ hỏi từng con số một.";
  if (error?.detail?.provider_http_status === 429 || /HTTP 429|quota|rate limit/i.test(text)) return "Dịch vụ AI đang hết lượt dùng cho lúc này, không phải do mạng của bạn. Thử lại sau vài phút.";
  if (/^AI_/.test(code) || /dịch vụ AI|AI/i.test(text) || (error?.status ?? 0) >= 500) return "Dịch vụ AI đang gặp lỗi, không phải do mạng của bạn. Thử lại sau ít phút.";
  if (/kết nối|mạng/i.test(text)) return "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.";
  return text || "Chưa gửi được câu hỏi. Thử lại sau ít phút.";
}
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

/** One honest sentence about where the numbers came from. */
export function confidenceOf(answer) {
  const data = (answer?.evidence ?? []).filter((item) => item.kind === "data");
  const quotes = (answer?.evidence ?? []).filter((item) => item.kind === "text");
  const formulas = realFormulas(answer);
  const typed = formulas.flatMap((formula) => formula.manual_numbers ?? []);
  if (answer?.not_found) return { kind: "warn", text: "Không tìm thấy số này trong báo cáo." };
  if (typed.length) return { kind: "warn", text: `Phép tính có số không lấy từ báo cáo: ${typed.map(showNumber).join(", ")}. Hãy kiểm tra lại.` };
  const estimated = data.filter((item) => (item.data_status && item.data_status !== "valid") || ESTIMATED.test(item.method_label ?? ""));
  if (estimated.length) return { kind: "warn", text: `Mình chưa chắc ${estimated.length} số đọc từ ảnh (biểu đồ hoặc bản scan). Chạm số để so với trang.` };
  // Where the numbers were read: a table, a chart, the running text, or several of them.
  const placeOf = (item) => item.method_label === "đọc từ văn bản" ? "đoạn văn"
    : item.source_type === "chart" || /nhãn|trục/.test(item.method_label ?? "") ? "biểu đồ" : "bảng";
  const places = ["bảng", "biểu đồ", "đoạn văn"].filter((place) => data.some((item) => placeOf(item) === place));
  const where = places.length ? places.join(places.length > 2 ? ", " : " và ") : "bảng";
  if (formulas.length) return { kind: "good", text: `Dựa trên ${formulas.reduce((count, formula) => count + (formula.inputs?.length ?? 0), 0) || data.length} số đọc trong ${where}, phép tính do máy làm. Chạm từng số để xem trên trang.` };
  if (data.length) return { kind: "good", text: `Đọc thẳng từ ${where} trong báo cáo.` };
  if (quotes.length) {
    const pages = [...new Set(quotes.map((item) => item.page).filter(Boolean))];
    return { kind: "warn", text: `Câu trả lời này không có con số nào để bạn kiểm.${pages.length ? ` Hãy đối chiếu trang ${pages.join(", ")}.` : ""}` };
  }
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
    unsure: Boolean((item.data_status && item.data_status !== "valid") || ESTIMATED.test(item.method_label ?? "")),
  }));
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

function ResultValue({ formula }) {
  const rows = scriptResultRows(formula);
  if (rows.length === 1 && !rows[0].name) return <b>= {rows[0].value}</b>;
  return <ul className="rd-result">{rows.map((row, index) => { const { name, unit } = resultName(row.name); return <li key={index}><span>{name}</span><b>{row.value}{unit && !String(row.value).includes(unit) ? unit : ""}</b></li>; })}</ul>;
}

/** The script with each value('ev-…') written as the cell it reads. */
function readableCode(formula) {
  const names = new Map((formula.inputs ?? []).map((input) => [input.evidence_key, readableLabel(input.label) || input.evidence_key]));
  return withoutDecimalRepr(formula.expression).replace(/value\((['"])(ev-[\w-]+)\1\)/g, (match, quote, key) => names.has(key) ? `«${names.get(key)}»` : match);
}

/** Where an answer's numbers and quotes come from, and how it calculated. */
function SourcesDetails({ answer, id, activeKey, onFocus, scanned, label = "Nguồn" }) {
  const rows = sourceRows(answer);
  const quotes = (answer?.evidence ?? []).filter((item) => item.kind === "text" && item.quote);
  const formulas = realFormulas(answer);
  const pages = [...new Set([...rows, ...quotes].map((item) => item.page).filter(Boolean))];
  if (!rows.length && !quotes.length && !formulas.length) return null;
  return <details className="rd-sources" onToggle={(event) => { if (event.currentTarget.open) { const node = event.currentTarget; window.requestAnimationFrame(() => node.scrollIntoView({ block: "nearest", behavior: scrollBehavior() })); } }}>
    <summary>{label}{pages.length ? ` · trang ${pages.join(", ")}` : ""}{formulas.length ? " · cách tính" : ""}</summary>
    {rows.length > 0 && <ul className="rd-source-list">{rows.map((row) => <li key={row.key}><button type="button" className={activeKey === row.key ? "active" : ""} onClick={() => onFocus(row)}><span>Trang {row.page} · {row.label || "số trong bảng"}</span><b>{row.value}</b></button></li>)}</ul>}
    {quotes.map((quote, index) => <button type="button" key={index} className="rd-quote" onClick={() => onFocus({ page: quote.page, boxes: quote.bbox ? [quote.bbox] : [], quote: quote.quote, label: `Đoạn văn ở trang ${quote.page}`, key: `quote-${id}-${index}` })}>“{quote.quote}”<small>Trang {quote.page}{scanned ? " · đọc từ ảnh scan, có thể sai chữ" : ""}</small></button>)}
    {formulas.map((formula, index) => <div key={index} className="rd-formula"><span>Cách tính</span>{formula.substitution && <p>{formula.substitution}</p>}<ResultValue formula={formula} />{formula.expression && <details><summary>Xem phép tính đầy đủ</summary><pre>{readableCode(formula)}</pre></details>}</div>)}
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
    return { value, label: known && name !== "Kết quả" ? name : "", parts: chip.parts, inputs, chip: { ...chip, value, result }, formula, result };
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
 * cell, "Đổi ô" when the AI read the wrong cell.
 */
function Headline({ headline, active, activeKey, onFocus, onPeek, onPick, busy, doubtful }) {
  const inputs = headline.inputs ?? [];
  const many = inputs.length > 1;
  return <div className={`rd-headline${headline.chip.unsure || doubtful ? " unsure" : ""}${active ? " active" : ""}${headline.original ? " changed" : ""}`}>
    <button type="button" className="rd-headline-value" aria-pressed={active} onClick={() => onFocus(headline.chip)}>
      <b>{doubtful && <i className="rd-mark unsure" aria-hidden="true">?</i>}{headline.value}{doubtful && <span className="rd-sr">, có thể không có nghĩa</span>}</b>
      {/* Words, not only a dashed outline: a swapped result must never read as the AI's answer. */}
      <span>{headline.original && "Kết quả sau khi bạn đổi ô · "}{headline.label}{headline.label && " · "}{many ? "tính từ các số dưới" : headline.formula ? `tính từ 1 số ở trang ${headline.chip.page}` : `trang ${headline.chip.page}`}<em>Xem trên trang</em></span>
    </button>
    {many && <ul className="rd-inputs">{inputs.map(({ index, ...input }) => {
      const chip = { page: input.page, boxes: input.bbox ? [input.bbox] : [], label: readableLabel(input.label), value: formatNumber(Number(input.value)), key: input.evidence_key };
      // Keyed by the input's place, so a swap keeps the same row and its "Đổi ô" can take focus back.
      return <li key={index} style={{ "--part": partColor(index) }}>
        <button type="button" className={`rd-input${activeKey === chip.key ? " active" : ""}`} aria-pressed={activeKey === chip.key} onClick={() => onFocus(chip)} {...peekProps(input.evidence_key, onPeek)}>
          <InputTag index={index} /><b>{chip.value}</b><small>{chip.label || `trang ${input.page}`}</small>
        </button>
        {onPick && <button type="button" className="rd-button small" aria-disabled={busy || undefined} onClick={() => { if (!busy) onPick(index); }} title={busy ? "Đang tính lại…" : "Lấy nhầm ô? Chọn ô đúng trên trang"} aria-label={`Đổi ô số ${index + 1}`}>Đổi ô</button>}
      </li>;
    })}</ul>}
  </div>;
}

function WorkingReply({ reply, onStop }) {
  const since = Date.parse(reply.created_at ?? "") || null;
  const seconds = useElapsed(since);
  const [stopping, setStopping] = useState(false);
  return <div className="rd-waiting"><span className="rd-spinner" aria-hidden="true" /><div><b>Đang trả lời…{since ? ` ${seconds} giây` : ""}</b><small>Câu trả lời sẽ hiện ở đây. Bạn vẫn đọc báo cáo được trong lúc chờ.</small></div>
    {onStop && <button type="button" className="rd-button" disabled={stopping} onClick={async () => { setStopping(true); try { await onStop(reply); } finally { setStopping(false); } }}>{stopping ? "Đang dừng…" : "Dừng"}</button>}
  </div>;
}

export function AnswerCard({ note, activeKey, onFocus, onAsk, onEdit, onOpenData, onStop, scanned, onPeek, onPick, pickBusy = false, swap, onUndoSwap }) {
  const { question, reply } = note;
  // Hooks before any early return: a reply goes from "working" to done in the same card.
  const [copied, setCopied] = useState(false);
  if (reply && (reply.status === "processing" || reply.structured_answer?.presentation === "processing_v1")) {
    return <article className="rd-card rd-qa waiting" aria-live="polite">{question && <p className="rd-question">{question.body}</p>}<WorkingReply reply={reply} onStop={onStop} /></article>;
  }
  const answer = reply?.structured_answer && reply.structured_answer.presentation !== "processing_v1" ? reply.structured_answer : null;
  const text = answer?.answer ?? reply?.body ?? "";
  const failed = reply && reply.status === "failed";
  const confidence = confidenceOf(answer);
  const rows = sourceRows(answer);
  const original = failed ? null : headlineOf(answer);
  const headline = original && swap ? swappedHeadline(original, swap.formula) : original;
  // Only a calculation can be run again on other cells; its place in the stored list names it to the server.
  const formulaIndex = original?.formula ? (answer.formulas ?? []).indexOf(original.formula) : -1;
  const quotes = (answer?.evidence ?? []).filter((item) => item.kind === "text" && item.quote);
  const pages = [...new Set([...rows, ...quotes].map((item) => item.page).filter(Boolean))];
  const copy = async () => { try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { /* clipboard refused */ } };

  return <article id={`note-${note.id}`} tabIndex={-1} className={`rd-card rd-qa${failed ? " failed" : ""}`}>
    {question && <p className="rd-question">{question.body}</p>}
    {failed && <><p className="rd-error-text">{friendlyError(reply.body?.replace(/^Không thể tạo câu trả lời:\s*/, ""))}</p><button type="button" className="rd-button" onClick={() => onAsk(question?.body ?? "")}>Hỏi lại</button></>}
    {!failed && reply && <>
      {headline && <Headline headline={headline} active={activeKey === headline.chip.key} activeKey={activeKey} onFocus={onFocus} onPeek={onPeek} busy={pickBusy} doubtful={Boolean(swap?.warning)}
        onPick={onPick && formulaIndex >= 0 && !reply.needs_update ? (index) => onPick({ note, base: original, headline, formulaIndex, index }) : null} />}
      {swap && <p className="rd-fyi changed">Bạn đã đổi ô: {swap.changes.map((change) => `${change.from} thành ${change.to}`).join("; ")}. Câu trả lời gốc ra {original.value}, phần chữ bên dưới vẫn theo số gốc. Đây chỉ là tính thử, không được lưu. {!pickBusy && <button type="button" className="rd-link" onClick={() => onUndoSwap(note.id)}>Hoàn tác</button>}</p>}
      {swap?.warning && <p className="rd-fyi warn"><i className="rd-mark unsure" aria-hidden="true">?</i><span>{swap.warning} Kết quả có thể không có nghĩa. Nếu không đúng ý, bấm Hoàn tác.</span></p>}
      <AnswerSentence text={text} answer={answer} activeKey={activeKey} onFocus={onFocus} />
      {confidence && <p className={`rd-confidence ${confidence.kind}`}><i aria-hidden="true" />{confidence.text}</p>}
      {reply.needs_update && <p className="rd-confidence neutral"><i aria-hidden="true" />Dữ liệu của báo cáo đã thay đổi sau câu trả lời này. Hỏi lại để có kết quả mới.</p>}
      {answer?.not_found && <div className="rd-next">
        <span>Thử tiếp</span>
        {pages.map((page) => <button key={page} type="button" onClick={() => onFocus({ page, boxes: [], label: `Trang ${page}`, key: `page-${note.id}-${page}` })}>Mở trang {page}</button>)}
        <button type="button" onClick={onOpenData}>Xem các số đã đọc</button>
        {question && <button type="button" onClick={() => onEdit(question.body)}>Hỏi cách khác</button>}
      </div>}
      <SourcesDetails answer={answer} id={note.id} activeKey={activeKey} onFocus={onFocus} scanned={scanned} />
      <div className="rd-actions">
        {question && !answer?.not_found && <button type="button" onClick={() => onEdit(question.body)}>Sửa câu hỏi</button>}
        <button type="button" onClick={copy}>{copied ? "Đã chép" : "Sao chép"}</button>
      </div>
    </>}
  </article>;
}

export function PendingCard({ item, onRetry, onDismiss }) {
  const seconds = useElapsed(item.status === "asking" ? item.startedAt : null);
  return <article className={`rd-card rd-qa${item.status === "failed" ? " failed" : " waiting"}`} aria-live="polite">
    <p className="rd-question">{item.question}</p>
    {item.status === "asking" && <div className="rd-waiting"><span className="rd-spinner" aria-hidden="true" /><div><b>Đang trả lời… {seconds} giây</b><small>{seconds < 45 ? "Thường mất 5 đến 40 giây. Bạn vẫn đọc báo cáo được trong lúc chờ." : "Lâu hơn bình thường. Dịch vụ AI có thể đang bận."}</small></div></div>}
    {item.status === "failed" && <><p className="rd-error-text">{friendlyError(item.errorObject ?? item.error)}</p><div className="rd-actions"><button type="button" className="rd-button" onClick={() => onRetry(item)}>Thử lại</button><button type="button" onClick={() => onDismiss(item.id)}>Bỏ qua</button></div></>}
  </article>;
}

const SECONDS_PER_PAGE = 12;

/** Progress of a new report. `uploading` is the moment before the server has the file. */
export function ReadingCard({ report, uploading = false }) {
  const since = report?.created_at ? Date.parse(report.created_at) : null;
  const seconds = useElapsed(since);
  const estimate = Math.max(15, (report?.page_count ?? 3) * SECONDS_PER_PAGE);
  const percent = uploading ? 5 : Math.min(95, Math.round((seconds / estimate) * 100));
  const late = seconds > estimate * 1.5;
  return <article className="rd-card rd-reading" aria-live="polite">
    <header><span className="rd-spinner large" aria-hidden="true" /><div><h3>{uploading ? `Đang tải lên ${report.file_name}` : "Đang đọc báo cáo"}</h3><p>{uploading ? `Gửi tệp lên máy chủ · đã ${seconds} giây` : <>{report.page_count ? `${report.page_count} trang · ` : ""}thường dưới {estimate} giây · đã {seconds} giây</>}</p></div></header>
    <div className="rd-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Tiến độ đọc ước tính"><span style={{ width: `${percent}%` }} /></div>
    <ol className="rd-steps">
      <li className={uploading ? "active" : "done"}>{uploading ? "Đang tải lên" : "Đã tải lên"}</li>
      <li className={uploading ? "" : "done"}>Mở được PDF, trang đang hiện bên trái</li>
      <li className={uploading ? "" : "active"}>Đọc chữ, bảng và số liệu</li>
      <li>Kiểm tra các dòng tổng</li>
    </ol>
    <p className="rd-hint">{uploading ? "Trang báo cáo sẽ hiện ngay khi tải lên xong." : late ? "Lâu hơn dự kiến, thường do trang scan. Vẫn đang đọc." : "Có thể gõ câu hỏi ngay. Đọc xong sẽ có tiếng chuông và thông báo."}</p>
  </article>;
}

export function FailedCard({ report, onRetry, busy }) {
  return <article className="rd-card rd-failed" role="alert">
    <h3>Chưa đọc được báo cáo này</h3>
    <p>Thường do PDF bị khoá, bị hỏng, hoặc là ảnh chụp quá mờ.</p>
    {onRetry && <button type="button" className="rd-button" onClick={() => onRetry(report)} disabled={busy}>Đọc lại</button>}
  </article>;
}

function CheckLine({ check, activeKey, onFocus, onDismiss }) {
  const chip = <NumberChip chip={check.chip} text={formatNumber(check.total)} active={activeKey === check.chip.key} onFocus={onFocus} />;
  const rounding = check.ok && Math.abs(check.diff) > 1e-9;
  if (rounding) return <li className="ok"><span aria-hidden="true">✓</span><p>{check.column}: {check.count} dòng cộng lại {formatNumber(check.sum)}, dòng tổng ghi {chip}. Lệch {formatNumber(Math.abs(check.diff))}, trong mức làm tròn.</p></li>;
  return check.ok
    ? <li className="ok"><span aria-hidden="true">✓</span><p>{check.column}: {check.count} dòng cộng lại đúng bằng dòng tổng {chip}</p></li>
    : <li className="bad"><span aria-hidden="true">!</span><p>{check.column}: các dòng cộng lại {formatNumber(check.sum)}, nhưng dòng tổng ghi {chip}. Lệch {formatNumber(Math.abs(check.diff))}.
      {onDismiss && <button type="button" className="rd-link rd-dismiss" onClick={() => onDismiss(check)} aria-label={`Không phải lỗi: ${check.column}`}>Không phải lỗi</button>}</p></li>;
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
export function BriefCard({ brief, briefing, dismissed = new Set(), onDismiss, onRestore, activeKey, onFocus, onAsk, onRetry, onOpenData, asked, collapsed, scanned, hint }) {
  const [open, setOpen] = useState(!collapsed);
  useEffect(() => { if (collapsed) setOpen(false); }, [collapsed]);
  const answer = brief?.status === "ready" ? brief.answer : null;
  const { main, caution } = splitCaution(answer?.answer);
  const bad = briefing?.checks.filter((check) => !check.ok && !dismissed.has(check.chip.key)) ?? [];
  const skipped = briefing?.checks.filter((check) => !check.ok && dismissed.has(check.chip.key)).length ?? 0;
  const good = briefing?.checks.filter((check) => check.ok) ?? [];
  const questions = (briefing?.suggestions?.length ? briefing.suggestions : FALLBACK_QUESTIONS).filter((question) => !asked?.has(question.trim()));
  return <article className={`rd-card rd-brief${open ? "" : " folded"}`} data-tour="briefing">
    <button type="button" className="rd-fold" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <span className="rd-kicker">Tóm tắt báo cáo</span>
      {!open && bad.length > 0 && <span className="rd-fold-status bad">{bad.length} chỗ không khớp</span>}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d={open ? "m6 15 6-6 6 6" : "m6 9 6 6 6-6"} /></svg>
    </button>
    {!open && answer && <p className="rd-brief-teaser">{firstSentence(main)}</p>}
    {open && <>
      {brief?.status === "loading" && <div className="rd-brief-loading" aria-live="polite"><span className="rd-spinner" aria-hidden="true" /><div><b>Đang đọc toàn bộ báo cáo để tóm tắt…</b><small>Thường mất 10 đến 30 giây. Bạn có thể hỏi ngay trong lúc chờ.</small></div></div>}
      {brief?.status === "loading" && <div className="rd-skeleton-lines" aria-hidden="true"><i /><i /><i /></div>}
      {brief?.status === "error" && <div className="rd-brief-error"><p className="rd-error-text">{/số bước|step|ASSISTANT_INCOMPLETE/i.test(`${brief.error?.code ?? ""} ${brief.error?.message ?? ""}`) ? "Báo cáo này dài và nhiều bảng, mình chưa tóm tắt xong trong lần này. Thử lại, hoặc hỏi từng ý bằng các câu gợi ý bên dưới." : `Chưa tóm tắt được. ${friendlyError(brief.error)}`}</p><button type="button" className="rd-button" onClick={onRetry}>Thử lại</button></div>}
      {answer && <>
        <AnswerSentence text={main} answer={answer} activeKey={activeKey} onFocus={onFocus} />
        {hint && /\d/.test(main) && <p className="rd-tip"><b>Mẹo</b>Chạm vào một số có nền xanh để xem ô gốc của nó trên trang.</p>}
        {caution.length > 0 && <div className="rd-caution"><strong>Cần chú ý</strong>{caution.map((line, index) => <p key={index}><Line text={line} answer={answer} activeKey={activeKey} onFocus={onFocus} /></p>)}</div>}
        <SourcesDetails answer={answer} id="brief" activeKey={activeKey} onFocus={onFocus} scanned={scanned} label="Nguồn của tóm tắt" />
      </>}
      {scanned && <p className="rd-banner">Đây là bản scan. Chữ được đọc từ ảnh nên có thể sai, nhất là số trong bảng. Hãy chạm số để tự kiểm trên trang.</p>}
      {bad.length > 0 && <div className="rd-alert"><strong>Mình thấy số không khớp trong báo cáo</strong><ul className="rd-checks">{bad.map((check) => <CheckLine key={check.chip.key} check={check} activeKey={activeKey} onFocus={onFocus} onDismiss={onDismiss} />)}</ul></div>}
      {skipped > 0 && <p className="rd-skipped">{skipped} chỗ không khớp bạn đã bỏ qua · <button type="button" className="rd-link" onClick={onRestore}>Hiện lại</button></p>}
      {!bad.length && !skipped && good.length > 0 && <p className="rd-verified"><span aria-hidden="true">✓</span>Mình đã tự cộng lại {good.length} dòng tổng trong bảng: đều khớp.</p>}
      {questions.length > 0 && <div className="rd-suggest"><span>Thử hỏi</span>{questions.map((question) => <button type="button" key={question} onClick={() => onAsk(question)}>{question}</button>)}</div>}
      <button type="button" className="rd-link rd-brief-data" onClick={onOpenData}>Xem tất cả số đã đọc</button>
    </>}
  </article>;
}
