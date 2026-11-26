import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { API, CLIENT_ERRORS, request } from "../../shared/api/client.js";
import { useTheme } from "../theme/ThemeProvider.jsx";
import { EvidenceList, ScriptCard } from "./ToolAnswer.jsx";
import { AnswerText } from "./AnswerText.jsx";
import { Icon } from "./Icon.jsx";
import { EvidenceDrawer } from "./EvidenceDrawer.jsx";
import { distinctFormulas, formatNumber } from "./format.js";
import { quoteBoxes } from "./pdfHighlight.js";

const SESSION_KEY = "sourcelens-active-session";
const DOCUMENT_KEY = "sourcelens-active-document";
const SESSION_SNAPSHOT_KEY = "sourcelens-session-snapshot-v1";
const SESSION_SNAPSHOT_TTL_MS = 60_000;
// Session list refreshes of this page, run one after another (see refresh).
let sessionListQueue = Promise.resolve();
const NOTICE_TIMEOUT_MS = 6_000;

function readSessionSnapshot() {
  try {
    const payload = JSON.parse(sessionStorage.getItem(SESSION_SNAPSHOT_KEY) || "null");
    if (!payload || !Array.isArray(payload.sessions)) return null;
    return {
      sessions: payload.sessions,
      savedAt: Number(payload.savedAt) || 0,
      stale: Date.now() - (Number(payload.savedAt) || 0) > SESSION_SNAPSHOT_TTL_MS,
    };
  } catch {
    return null;
  }
}

// Questions the server has not saved yet: the one still being sent and the
// ones that failed. JSON mode answers inside the request and saves nothing
// until it ends, so after a reload only this tab knows them. Each keeps its
// Idempotency-Key, so sending it again returns the answer the server may have
// saved meanwhile, and the question it was asked after, so it keeps its place.
// After a reload a question still being sent is sent again while it is young;
// any other one comes back as a failed question with its retry button.
const UNSAVED_QUESTIONS_KEY = "sourcelens-unsaved-questions-v1";
const RESEND_AFTER_RELOAD_MS = 10 * 60_000;

function readUnsavedQuestions() {
  try {
    const value = JSON.parse(sessionStorage.getItem(UNSAVED_QUESTIONS_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item) => item?.id && item.question && item.key && item.session_id && item.document_id) : [];
  } catch { return []; }
}

function updateUnsavedQuestions(change) {
  try {
    const next = change(readUnsavedQuestions());
    if (next.length) sessionStorage.setItem(UNSAVED_QUESTIONS_KEY, JSON.stringify(next));
    else sessionStorage.removeItem(UNSAVED_QUESTIONS_KEY);
  } catch { /* storage disabled: a reload then loses only the unsaved questions */ }
}

/** The two chat messages of a question that was not saved. */
function failedTurn(item) {
  const scope = { session_id: item.session_id, document_id: item.document_id };
  return [
    { id: item.id, role: "user", body: item.question, ...scope, after_question_id: item.after ?? null, pending: false, failed: true, status: "failed" },
    { id: item.answer_id, role: "assistant", reply_to_message_id: item.id, body: item.error || CLIENT_ERRORS.unknown, ...scope, pending: false, failed: true, status: "failed", structured_answer: null,
      retry: { question: item.question, idempotencyKey: item.key, scope, after: item.after ?? null, replaces: [item.id, item.answer_id] } },
  ];
}

/**
 * Chat order: saved questions in server order, each followed by its replies.
 * A question not saved yet sits right after the question that was last when
 * it was sent; one without such a question goes last.
 */
function orderConversation(saved, unsaved) {
  const all = [...saved, ...unsaved];
  const replies = new Map();
  for (const message of all) {
    if (message.role === "assistant" && message.reply_to_message_id) replies.set(message.reply_to_message_id, [...(replies.get(message.reply_to_message_id) ?? []), message]);
  }
  const questionIds = new Set(all.filter((message) => message.role === "user").map((message) => message.id));
  const unsavedAfter = new Map();
  for (const message of unsaved) {
    if (message.role !== "user") continue;
    const anchor = questionIds.has(message.after_question_id) ? message.after_question_id : "end";
    unsavedAfter.set(anchor, [...(unsavedAfter.get(anchor) ?? []), message]);
  }
  // A question's turn runs until the next question, so replies without a
  // link (older data) stay with it; unsaved questions follow the whole turn.
  const ordered = [];
  let openTurn = null;
  const closeTurn = () => {
    const question = openTurn;
    openTurn = null;
    (unsavedAfter.get(question) ?? []).forEach(place);
  };
  function place(message) {
    if (message.role === "assistant" && questionIds.has(message.reply_to_message_id)) return;
    if (message.role === "user") closeTurn();
    ordered.push(message);
    if (message.role !== "user") return;
    ordered.push(...(replies.get(message.id) ?? []));
    openTurn = message.id;
  }
  saved.forEach(place);
  closeTurn();
  (unsavedAfter.get("end") ?? []).forEach(place);
  closeTurn();
  unsaved.filter((message) => message.role !== "user").forEach(place);
  return ordered;
}

function writeSessionSnapshot(sessions) {
  try {
    // Keep the fast-start cache to workspace/document metadata. Chat history is
    // fetched from the API so a tab cannot accidentally retain sensitive text.
    const metadata = sessions.map((session) => ({ ...session, messages: [] }));
    sessionStorage.setItem(SESSION_SNAPSHOT_KEY, JSON.stringify({ savedAt: Date.now(), sessions: metadata }));
  } catch {
    // Storage can be disabled or full; the network path remains authoritative.
  }
}

// Why an edit was not carried over to a new reading that is ready. (A failed
// reading carries nothing over: the edits stay in document.pending_edits.)
const EDIT_NOT_KEPT_REASONS = {
  NOT_IN_NEW_READING: "không còn trong lần đọc mới",
  LOCATION_CHANGED: "vị trí đã thay đổi",
};

/** What the latest re-extraction did, once its new reading is ready. */
function rereadSummary(document) {
  const run = document.extraction_history?.at(-1);
  const flagged = run?.affected_message_ids?.length ?? 0;
  return `Đã đọc lại ${document.file_name}: ${document.numeric_evidence_count ?? 0} số liệu.${carriedEditsSummary(run)}${flagged ? ` ${flagged} câu trả lời dùng số đã thay đổi cần cập nhật.` : ""}`;
}

/** What happened to the user's edits in the latest re-extraction. */
function carriedEditsSummary(run) {
  const kept = run?.edits_carried_over;
  const lost = run?.edits_not_carried_over;
  if (!Array.isArray(kept) || !Array.isArray(lost) || (!kept.length && !lost.length)) return "";
  const parts = [];
  if (kept.length) parts.push(`Giữ lại ${kept.length} số đã sửa`);
  if (lost.length) {
    const counts = new Map();
    for (const item of lost) {
      const reason = EDIT_NOT_KEPT_REASONS[item.code] ?? "không khớp lần đọc mới";
      counts.set(reason, (counts.get(reason) ?? 0) + 1);
    }
    parts.push([...counts].map(([reason, count]) => `${count} số không giữ được vì ${reason}`).join(", "));
  }
  return ` ${parts.join("; ")}.`;
}

function formatBytes(value = 0) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function processingLabel(status) {
  // Keep implementation details (indexing/extraction) out of customer copy.
  // The job center still exposes the technical state for operators.
  return ({
    queued: "Đang chuẩn bị tài liệu",
    processing: "Đang đọc tài liệu",
    ready: "Sẵn sàng để hỏi",
    failed: "Không thể đọc — thử lại",
  }[status] ?? "Đang kiểm tra");
}

// Errors from request() already carry the text to show: the server's
// detail.message, or the client's own text for network problems.
function userFacingError(value) {
  const text = typeof value === "string" ? value : value?.message;
  return text?.trim() || CLIENT_ERRORS.unknown;
}

function normalizedBbox(value) {
  const raw = Array.isArray(value) ? value : [value?.x0, value?.y0, value?.x1, value?.y1];
  if (raw.length !== 4 || raw.some((item) => !Number.isFinite(Number(item)))) return null;
  const [x0, y0, x1, y1] = raw.map((item) => Math.max(0, Math.min(1, Number(item))));
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

function presentationAnswer(message) {
  if (message?.status === "processing" || message?.structured_answer?.presentation === "processing_v1") return { pending: true };
  if (message?.structured_answer && message.mode === "deterministic_text_retrieval") {
    return { ...message.structured_answer, presentation: "retrieval_excerpt", retrieved_excerpt: message.body ?? message.structured_answer.retrieved_excerpt ?? "" };
  }
  if (message?.structured_answer) return message.structured_answer;
  if (message?.role !== "assistant" || message?.mode !== "deterministic_text_retrieval") return null;
  const page = message.citations?.[0]?.page;
  return {
    presentation: "retrieval_excerpt",
    retrieved_excerpt: message.body ?? "",
    answer: page ? `Có nội dung liên quan ở trang ${page}.` : "Có nội dung liên quan trong tài liệu.",
    summary: "Câu trả lời offline chỉ trình bày dữ liệu đã truy hồi, không suy diễn thêm.",
    sections: [{
      heading: page ? `Trích đoạn liên quan · trang ${page}` : "Trích đoạn liên quan",
      points: [],
      evidence_pages: page ? [page] : [],
    }],
    formulas: [],
    tables: [],
    claims: [],
    warnings: ["Đây là trích đoạn trực tiếp từ tài liệu; chưa có phân tích hoặc tính toán bổ sung."],
    cited_pages: page ? [page] : [],
  };
}

function PerformanceDrawer({ metrics, onClose, onClear }) {
  if (!metrics) return null;
  const durations = metrics.filter((item) => item.ok && Number.isFinite(item.duration_ms)).map((item) => item.duration_ms);
  const average = durations.length ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length) : 0;
  const latest = durations[0] ?? 0;
  const failures = metrics.filter((item) => !item.ok).length;
  return <section className="performance-drawer" role="dialog" aria-modal="true" aria-label="Hiệu năng hệ thống">
    <header className="performance-header"><div><span className="audit-kicker">SYSTEM PERFORMANCE</span><h3>Độ trễ & luồng thao tác</h3><small>{metrics.length} request gần nhất · đo từ trình duyệt</small></div><div className="performance-actions"><button type="button" onClick={onClear}>Xóa</button><button type="button" aria-label="Đóng performance" onClick={onClose}><Icon name="close" size={15} /></button></div></header>
    <div className="performance-summary"><div><span>Gần nhất</span><b>{latest ? `${latest} ms` : "—"}</b></div><div><span>Trung bình</span><b>{average ? `${average} ms` : "—"}</b></div><div><span>Lỗi</span><b className={failures ? "metric-bad" : ""}>{failures}</b></div></div>
    <div className="performance-list">{metrics.length ? metrics.map((item) => <article className={`performance-row ${item.ok ? "ok" : "failed"}`} key={item.request_id}><span className="performance-dot"></span><div><strong>{item.method} {item.path}</strong><small>{new Date(item.at).toLocaleTimeString()} · {item.status || item.error}</small></div><b>{item.duration_ms} ms</b></article>) : <p className="performance-empty">Chưa có request. Hãy tải tài liệu hoặc gửi một câu hỏi.</p>}</div>
    <footer className="performance-footer">Latency đo từ lúc UI gửi request đến khi nhận response. Không bao gồm thời gian người dùng đọc câu trả lời.</footer>
  </section>;
}

function JobCenterDrawer({ jobs, busy, onClose, onAction }) {
  if (!jobs) return null;
  const active = jobs.filter((job) => ["queued", "running"].includes(job.status));
  return <section className="job-center-drawer" role="dialog" aria-modal="true" aria-labelledby="job-center-title">
    <header className="job-center-header"><div><span className="audit-kicker">TRUNG TÂM TÁC VỤ</span><h3 id="job-center-title">Tác vụ đang chạy</h3><small>Theo dõi việc chuẩn bị tài liệu và câu trả lời</small></div><button type="button" aria-label="Đóng trung tâm tác vụ" onClick={onClose}><Icon name="close" size={15} /></button></header>
    <div className="job-center-summary"><span><i></i>{active.length} đang xử lý</span><small>Trạng thái được lưu bền theo tài khoản</small></div>
    <div className="job-center-list">{jobs.length ? jobs.map((job) => <article className="job-center-row" key={job.id}><div className={`job-center-status ${job.status}`}><span></span></div><div className="job-center-main"><strong>{["document_extraction", "extract_document"].includes(job.kind) ? "Chuẩn bị tài liệu" : ["answer_generation", "generate_answer"].includes(job.kind) ? "Tạo câu trả lời" : "Tác vụ đang chạy"}</strong><small>{job.status === "queued" ? "Đang chờ xử lý" : job.status === "running" ? "Đang xử lý" : job.status === "failed" ? "Cần thử lại" : "Đã hoàn tất"}</small></div><div className="job-center-actions">{["queued", "running"].includes(job.status) && <button type="button" onClick={() => onAction(job, "cancel")} disabled={busy}>Huỷ</button>}{job.status === "failed" && <button type="button" onClick={() => onAction(job, "retry")} disabled={busy}>Thử lại</button>}</div></article>) : <div className="job-center-empty"><span>✓</span><p>Không có tác vụ gần đây.</p><small>Khi tải PDF hoặc hỏi AI, trạng thái sẽ xuất hiện ở đây.</small></div>}</div>
  </section>;
}

function RetrievalExcerpt({ answer }) {
  const excerpt = String(answer?.retrieved_excerpt ?? "").trim();
  if (!excerpt) return null;
  return <section className="retrieval-excerpt-card" aria-label="Trích đoạn nguồn">
    <div className="retrieval-excerpt-meta"><span className="retrieval-source-dot"></span><span>NGUỒN TRUY HỒI</span><small>Văn bản gốc · không diễn giải</small></div>
    <details>
      <summary><span>Xem trích đoạn nguồn</span><Icon name="arrowRight" size={13} /></summary>
      <pre>{excerpt}</pre>
    </details>
  </section>;
}

function StructuredAnswer({ answer, fallback, onCitation, evidenceByKey, busy, onAsk }) {
  if (answer?.pending) return <div className="typing-indicator" aria-live="polite"><span className="typing-dots"><i></i><i></i><i></i></span><span>Đang tạo câu trả lời</span></div>;
  if (!answer && typeof fallback === "string" && fallback.startsWith("Không thể tạo câu trả lời:")) return <div className="answer-failure" role="alert"><Icon name="refresh" size={14} /><span>{fallback}</span></div>;
  if (!answer) return <p>{fallback}</p>;
  if (answer.presentation === "retrieval_excerpt") return <div className="structured-answer retrieval-answer">
    <AnswerText text={answer.answer} />
    {answer.summary && <p className="answer-summary">{answer.summary}</p>}
    <RetrievalExcerpt answer={answer} />
    {answer.warnings?.filter(Boolean).length > 0 && <div className="answer-status-note"><Icon name="trace" size={13} /><span>{answer.warnings.filter(Boolean)[0]}</span></div>}
  </div>;
  const warnings = answer.warnings?.filter(Boolean) ?? [];
  // A clarifying question offers answers; choosing one asks it as the next question.
  const options = (answer.options ?? []).filter((option) => typeof option === "string" && option.trim());
  return <div className="structured-answer">
    <AnswerText text={answer.answer} />
    {options.length > 0 && onAsk && <div className="answer-options" role="group" aria-label="Chọn một câu trả lời">{options.map((option) => <button type="button" key={option} disabled={busy} onClick={() => onAsk(option)}>{option}</button>)}</div>}
    {answer.evidence?.length > 0 && <EvidenceList items={answer.evidence} evidenceByKey={evidenceByKey} onCitation={onCitation} />}
    {answer.summary && <p className="answer-summary">{answer.summary}</p>}
    {answer.claims?.length > 0 && <section className="answer-section answer-claims"><h4>Nhận định và căn cứ</h4>{answer.claims.map((claim, index) => <div className="claim-card" key={`${claim.claim}-${index}`}>
      <p>{claim.claim}</p>
      {claim.evidence_quotes?.map((quote, quoteIndex) => <button className="evidence-quote" key={`${quote}-${quoteIndex}`} onClick={() => onCitation?.(claim.evidence_pages?.[quoteIndex] ?? claim.evidence_pages?.[0], quote)}><span className="evidence-quote-label"><Icon name="link" size={12} /> Trích dẫn</span><span>“{quote}”</span></button>)}
      {claim.evidence_pages?.length > 0 && <div className="evidence-pages">{claim.evidence_pages.map((page) => <button className="citation" key={page} onClick={() => onCitation?.(page, claim.evidence_quotes?.[0] ?? "")}><Icon name="link" size={12} /> Trang {page}</button>)}</div>}
    </div>)}</section>}
    {answer.sections?.map((section, index) => <section className="answer-section" key={`${section.heading}-${index}`}><h4>{section.heading}</h4>{section.points?.filter(Boolean).length > 0 && <ul>{section.points.filter(Boolean).map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}</ul>}</section>)}
    {answer.formulas?.length > 0 && <section className="answer-section"><h4>Công thức và tính toán</h4>{distinctFormulas(answer.formulas).map((formula, index) => formula.inputs ? <ScriptCard formula={formula} onCitation={onCitation} key={`script-${index}`} /> : <div className="formula-card" key={`${formula.name}-${index}`}><strong>{formula.name}</strong><code>{formula.expression}</code><span>Thay số: {formula.substitution || "Chưa đủ toán hạng"}</span><b>Kết quả: {formatNumber(formula.result) || "Không xác định"}{formula.unit ? ` ${formula.unit}` : ""}</b>{["verified", "succeeded"].includes(formula.calculation?.status) ? <em className="formula-verified">✓ Đã tính lại: {formatNumber(formula.calculation.computed_result)}{formula.calculation.unit ? ` ${formula.calculation.unit}` : ""}</em> : <em className="formula-unverified">Chưa tính lại được</em>}</div>)}</section>}
    {answer.tables?.map((table, index) => <section className="answer-section" key={`${table.title}-${index}`}><h4>{table.title}</h4><div className="answer-table-wrap"><table className="answer-table"><thead><tr>{table.columns?.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{table.rows?.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div></section>)}
    {warnings.length > 0 && <div className="answer-warnings"><strong>Lưu ý</strong><ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
  </div>;
}

function ChatMessage({ message, busy, evidenceByKey, onCitation, onStop, onRetry, onEditQuestion, onCopy, onAsk }) {
  const isUser = message.role === "user";
  const failed = message.failed || message.status === "failed";
  const processing = !isUser && message.status === "processing";
  const done = !isUser && message.body && !message.pending && !failed && !processing;
  return <article data-message-id={message.id} className={`message ${message.role} ${failed ? "failed" : ""}`}>
    <span className="message-avatar" aria-hidden="true">{isUser ? "B" : "S"}</span>
    <div>
      <small>{isUser ? "Bạn" : "Trợ lý SourceLens"}</small>
      {!isUser && message.failed
        ? <div className="answer-failure" role="alert"><Icon name="refresh" size={14} /><span>{message.body}</span></div>
        : <StructuredAnswer answer={presentationAnswer(message)} fallback={message.body} evidenceByKey={evidenceByKey} onCitation={onCitation} busy={busy} onAsk={onAsk} />}
      {processing && <button className="retry-answer-button" type="button" onClick={() => onStop(message)}>Dừng trả lời</button>}
      {failed && !isUser && <button className="retry-answer-button" type="button" onClick={() => onRetry(message)} disabled={busy}><Icon name="refresh" size={13} /> Thử lại</button>}
      {isUser && !message.pending && <button className="message-icon-button" type="button" aria-label="Sửa câu hỏi" title="Sửa câu hỏi" onClick={() => onEditQuestion(message.body)}><Icon name="edit" size={14} /></button>}
      {done && <button className="message-icon-button" type="button" aria-label="Sao chép câu trả lời" title="Sao chép câu trả lời" onClick={() => onCopy(message.body)}><Icon name="copy" size={14} /></button>}
      {message.needs_update && <div className="answer-status-note stale-answer"><Icon name="refresh" size={13} /><span>Dữ liệu nguồn đã thay đổi; câu trả lời này cần được cập nhật.</span></div>}
      {!message.structured_answer?.evidence?.length && message.citations?.map((citation, index) => <button className="citation" type="button" key={index} onClick={() => onCitation(citation.page, citation.quote ?? "", citation.bbox)}><Icon name="link" size={12} /> Trang {citation.page}</button>)}
    </div>
  </article>;
}

/** Scrolls a page area into view when part of it is off screen (stacked layout on narrow screens). */
function bringIntoView(node) {
  const rect = node?.getBoundingClientRect();
  if (rect && (rect.top < 0 || rect.bottom > window.innerHeight)) node.scrollIntoView({ block: "start", behavior: "smooth" });
}

const PDF_ERRORS = {
  open: "Không mở được tệp PDF. Hãy thử lại.",
  invalid: "Tệp này không phải PDF hợp lệ hoặc đã bị hỏng.",
  draw: "Không vẽ được trang PDF này.",
};

// pdf.js fetches the file itself and keeps only the HTTP status of a failed
// request. Ask the server again, for one byte, so the reader shows the
// server's own message like every other request does.
async function pdfOpenError(reason, path) {
  if (reason?.status) {
    try { await request(path, { headers: { Range: "bytes=0-0" } }); }
    catch (error) { return error.message; }
  }
  return reason?.name === "InvalidPDFException" ? PDF_ERRORS.invalid : PDF_ERRORS.open;
}

const clampScale = (value) => Math.max(.35, Math.min(2.5, value));

function PdfViewer({ document, sessionId, citationPage, evidenceQuote, evidenceBbox, onReextract, reextractDisabled }) {
  const viewportRef = useRef(null);
  const canvasRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [pdf, setPdf] = useState(null);
  const [page, setPage] = useState(1);
  // "fit" follows the pane width; a number is a zoom the user chose.
  const [zoom, setZoom] = useState("fit");
  const [fitScale, setFitScale] = useState(1);
  const fitScaleRef = useRef(1);
  const scale = zoom === "fit" ? fitScale : zoom;
  const zoomBy = (step) => setZoom((current) => clampScale((current === "fit" ? fitScale : current) + step));
  const [rotation, setRotation] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [textItems, setTextItems] = useState([]);
  const [textViewport, setTextViewport] = useState(null);
  const [citationQuote, setCitationQuote] = useState("");
  const [citationBbox, setCitationBbox] = useState(null);
  const dragRef = useRef(null);
  // Set by a new citation; cleared once its highlight is scrolled into view.
  const centerHighlightRef = useRef(false);

  useEffect(() => {
    let disposed = false;
    setPdf(null); setPage(1); setZoom("fit"); setError(""); setTextItems([]); setTextViewport(null); setCitationQuote(""); setCitationBbox(null);
    if (!document) { setLoading(false); return undefined; }
    const relativeFileUrl = document.file_url || `/api/v1/sessions/${sessionId}/documents/${document.id}/file`;
    let fileUrl;
    try { fileUrl = new URL(relativeFileUrl, API).toString(); } catch { fileUrl = ""; }
    if (!relativeFileUrl || relativeFileUrl.includes("undefined") || !/^https?:/.test(fileUrl)) {
      setLoading(false); setError(PDF_ERRORS.open); return undefined;
    }
    setLoading(true);
    let task;
    import("pdfjs-dist").then((pdfjs) => {
      if (disposed) return null;
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      // The file endpoint is protected by the HttpOnly session cookie. PDF.js
      // must opt in to credentials when it performs its own URL request.
      task = pdfjs.getDocument({ url: fileUrl, withCredentials: true });
      return task.promise;
    }).then((loaded) => {
      if (loaded && !disposed) { setPdf(loaded); setLoading(false); }
    }).catch(async (reason) => {
      const message = await pdfOpenError(reason, relativeFileUrl);
      if (!disposed) { setError(message); setLoading(false); }
    });
    return () => { disposed = true; task?.destroy(); };
  }, [document?.id, document?.file_url, sessionId]);

  useEffect(() => {
    if (!pdf || !canvasRef.current) return undefined;
    let cancelled = false;
    setTextItems([]);
    pdf.getPage(page).then((pdfPage) => {
      if (cancelled) return;
      const viewport = pdfPage.getViewport({ scale, rotation });
      const canvas = canvasRef.current;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      setTextViewport({ width: viewport.width, height: viewport.height, transform: viewport.transform, rotation, scale, page });
      if (rotation === 0) pdfPage.getTextContent().then((content) => setTextItems(content.items.filter((item) => item.str?.trim()))).catch(() => setTextItems([]));
      else setTextItems([]);
      const context = canvas.getContext("2d");
      renderTaskRef.current?.cancel();
      renderTaskRef.current = pdfPage.render({ canvasContext: context, viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] });
      renderTaskRef.current.promise.catch((reason) => { if (reason?.name !== "RenderingCancelledException") setError(PDF_ERRORS.draw); });
    }).catch(() => { if (!cancelled) setError(PDF_ERRORS.draw); });
    return () => { cancelled = true; renderTaskRef.current?.cancel(); };
  }, [pdf, page, scale, rotation]);

  // The page fills the pane width, and keeps filling it when the pane resizes.
  useEffect(() => {
    const node = viewportRef.current;
    if (!pdf || !node) return undefined;
    let pageWidth = 0;
    let cancelled = false;
    const measure = () => {
      const mat = node.querySelector(".canvas-mat");
      const style = mat ? getComputedStyle(mat) : null;
      const padding = style ? parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) : 0;
      if (!pageWidth || !node.clientWidth) return;
      fitScaleRef.current = clampScale((node.clientWidth - padding) / pageWidth);
      setFitScale(fitScaleRef.current);
    };
    pdf.getPage(page).then((pdfPage) => { if (!cancelled) { pageWidth = pdfPage.getViewport({ scale: 1, rotation }).width; measure(); } }).catch(() => {});
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(node);
    return () => { cancelled = true; observer?.disconnect(); };
  }, [pdf, page, rotation]);

  useEffect(() => {
    if (!citationPage || !pdf) return;
    setCitationQuote(evidenceQuote || "");
    setCitationBbox(normalizedBbox(evidenceBbox));
    setPage(Math.min(Math.max(1, citationPage), pdf.numPages));
    // A page fitted to a phone's width prints numbers a few pixels tall:
    // show a citation at full size, centred on it, instead.
    setZoom((current) => (current === "fit" && fitScaleRef.current < 1 ? 1 : current));
    centerHighlightRef.current = true;
  }, [citationPage, evidenceQuote, evidenceBbox, pdf]);

  const derivedBoxes = textViewport ? quoteBoxes(textItems, textViewport, citationQuote) : [];
  // The quote found in the page text is the most exact place; the stored box
  // covers numbers (no quote) and pages whose text cannot be matched.
  const evidenceBoxes = rotation === 0 ? (derivedBoxes.length ? derivedBoxes : citationBbox ? [citationBbox] : []) : [];
  const highlightKey = evidenceBoxes.map((box) => box.join(",")).join(";");
  useEffect(() => {
    const viewport = viewportRef.current;
    const box = viewport?.querySelector(".evidence-box");
    // Wait until the cited page itself is laid out at the current zoom.
    if (!centerHighlightRef.current || !box || textViewport?.page !== page || textViewport?.scale !== scale) return;
    centerHighlightRef.current = false;
    const boxRect = box.getBoundingClientRect();
    const viewRect = viewport.getBoundingClientRect();
    // Centre the box vertically. Sideways, move only as far as needed to show
    // it, so the row labels to its left stay in view whenever they fit.
    const margin = 24;
    const boxLeft = viewport.scrollLeft + boxRect.left - viewRect.left;
    let left = viewport.scrollLeft;
    if (boxLeft + boxRect.width > left + viewport.clientWidth - margin) left = boxLeft + boxRect.width - viewport.clientWidth + margin;
    if (boxLeft < left + margin) left = boxLeft - margin;
    viewport.scrollTo({
      top: viewport.scrollTop + boxRect.top - viewRect.top - (viewport.clientHeight - boxRect.height) / 2,
      left: Math.max(0, left),
      behavior: "smooth",
    });
  }, [highlightKey, page, scale, textViewport]);
  const textLayer = textViewport && <div className="pdf-text-layer" aria-hidden="true" style={{ width: textViewport.width, height: textViewport.height, left: "50%", top: 30, transform: "translateX(-50%)" }}><div className="evidence-box-layer">{evidenceBoxes.map((box, index) => <span className="evidence-box" key={`${box.join("-")}-${index}`} style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }} />)}</div></div>;

  if (!document) return <div className="empty-reader"><div className="empty-icon">PDF</div><h2>Chọn hoặc thêm tài liệu</h2><p>Tài liệu được lưu theo phiên làm việc và mở trực tiếp trong trình đọc PDF.</p></div>;

  return <section className="reader-shell">
    <header className="reader-toolbar">
      <div className="reader-file"><strong>{document.file_name}</strong><span>{formatBytes(document.byte_size)} · {processingLabel(document.extraction_status)}</span></div>
      {["queued", "processing"].includes(document.extraction_status)
        ? <span className="reextract-status" role="status"><span className="typing-dots" aria-hidden="true"><i></i><i></i><i></i></span>{processingLabel(document.extraction_status)}…</span>
        : onReextract && <button className="reextract-button" type="button" title="Đọc lại tài liệu và lập lại bảng số liệu" disabled={reextractDisabled} onClick={() => onReextract(document)}><Icon name="refresh" size={13} /> Trích xuất lại</button>}
      <div className="page-control"><button aria-label="Trang trước" title="Trang trước" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><Icon name="arrowLeft" /></button><span>{page} / {pdf?.numPages ?? document.page_count ?? "—"}</span><button aria-label="Trang sau" title="Trang sau" disabled={!pdf || page >= pdf.numPages} onClick={() => setPage((value) => value + 1)}><Icon name="arrowRight" /></button></div>
      <div className="zoom-control"><button aria-label="Thu nhỏ" title="Thu nhỏ" onClick={() => zoomBy(-.15)}><Icon name="minus" /></button><span>{Math.round(scale * 100)}%</span><button aria-label="Phóng to" title="Phóng to" onClick={() => zoomBy(.15)}><Icon name="plus" /></button><button aria-label="Vừa chiều rộng" title="Vừa chiều rộng" aria-pressed={zoom === "fit"} onClick={() => setZoom("fit")}><Icon name="fit" /></button><button aria-label="Xoay tài liệu" title="Xoay tài liệu" onClick={() => setRotation((value) => (value + 90) % 360)}><Icon name="rotate" /></button></div>
    </header>
    <div className={`pdf-viewport ${dragRef.current ? "dragging" : ""}`} ref={viewportRef}
      onPointerDown={(event) => { const node = viewportRef.current; dragRef.current = { x: event.clientX, y: event.clientY, left: node.scrollLeft, top: node.scrollTop }; node.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => { if (!dragRef.current) return; const node = viewportRef.current; node.scrollLeft = dragRef.current.left - (event.clientX - dragRef.current.x); node.scrollTop = dragRef.current.top - (event.clientY - dragRef.current.y); }}
      onPointerUp={() => { dragRef.current = null; }}
      onPointerCancel={() => { dragRef.current = null; }}
      onWheel={(event) => { if (!event.ctrlKey) return; event.preventDefault(); zoomBy(event.deltaY < 0 ? .1 : -.1); }}>
      {loading && <div className="reader-loading" role="status">Đang mở tài liệu…</div>}
      {error && <div className="reader-error" role="alert">{error}</div>}
      <div className="canvas-mat"><canvas key={document.id} ref={canvasRef} />{textLayer}</div>
    </div>
  </section>;
}

function ProfileMenu({ user, onSignOut, onNavigate }) {
  const [open, setOpen] = useState(false);
  const [profile, setProfile] = useState(user);
  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const menuRef = useRef(null);
  const nameId = useId();
  useEffect(() => { setProfile(user); setDisplayName(user?.display_name ?? ""); }, [user]);
  // Escape or a click outside closes the menu, like the other popovers.
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event) => { if (!menuRef.current?.contains(event.target)) setOpen(false); };
    const onKey = (event) => { if (event.key === "Escape") { setOpen(false); menuRef.current?.querySelector(".profile-chip")?.focus(); } };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onPointer); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const initial = (profile?.display_name || profile?.email || "S").trim().slice(0, 1).toUpperCase();
  const saveProfile = async (event) => {
    event.preventDefault();
    if (!displayName.trim()) return;
    setSaving(true); setError("");
    try {
      const body = await request("/api/v1/settings/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: displayName.trim() }) });
      setProfile(body.user); setEditing(false);
    } catch (reason) { setError(reason.message); }
    finally { setSaving(false); }
  };
  const accountName = profile?.display_name || profile?.email || "Workspace cá nhân";
  return <div className="profile-menu" ref={menuRef}>
    <button className="profile-chip" type="button" aria-expanded={open} aria-label={`Tài khoản: ${accountName}`} onClick={() => setOpen((value) => !value)}>
      <span className="profile-avatar">{initial}</span>
      <span className="profile-copy"><b>{profile?.display_name || "Workspace cá nhân"}</b><small>{profile?.email || "Chế độ demo"}</small></span>
      <Icon name="chevronDown" size={13} />
    </button>
    {open && <div className="profile-popover">
      <div className="profile-summary"><span className="profile-avatar large">{initial}</span><div><b>{profile?.display_name || "Workspace cá nhân"}</b><small>{profile?.email || "Không yêu cầu đăng nhập"}</small></div></div>
      <div className="profile-meta"><Icon name="user" size={14} /><span>Tài khoản và dữ liệu được phân tách theo phiên làm việc.</span></div>
      {onNavigate && !editing && <><button className="profile-manage" type="button" onClick={() => { setOpen(false); onNavigate("/app/settings/profile"); }}><Icon name="user" size={14} /> Hồ sơ tài khoản</button><button className="profile-manage" type="button" onClick={() => { setOpen(false); onNavigate("/app/settings/preferences"); }}><Icon name="settings" size={14} /> Tuỳ chọn giao diện</button><button className="profile-manage" type="button" onClick={() => { setOpen(false); onNavigate("/app/settings/security"); }}><Icon name="trace" size={14} /> Bảo mật</button></>}
      {onSignOut && !editing && <button className="profile-manage" type="button" onClick={() => setEditing(true)}><Icon name="edit" size={14} /> Chỉnh sửa nhanh</button>}
      {onSignOut && editing && <form className="profile-edit-form" onSubmit={saveProfile}><label htmlFor={nameId}>Tên hiển thị</label><input id={nameId} autoFocus value={displayName} maxLength={120} onChange={(event) => setDisplayName(event.target.value)} />{error && <p role="alert">{error}</p>}<div><button type="button" onClick={() => { setDisplayName(profile?.display_name ?? ""); setEditing(false); setError(""); }}>Hủy</button><button type="submit" disabled={saving || !displayName.trim()}>{saving ? "Đang lưu…" : "Lưu hồ sơ"}</button></div></form>}
      {onSignOut && <button className="profile-signout" type="button" onClick={onSignOut}><Icon name="logout" size={15} /> Đăng xuất</button>}
    </div>}
  </div>;
}

/** Resource actions live in a body-level portal so a scrolling sidebar cannot clip them. */
function ActionMenu({ label, onRename, onDelete }) {
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  useEffect(() => {
    if (!open) return undefined;
    const closeOnPointer = (event) => {
      if (triggerRef.current?.contains(event.target) || menuRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    const closeOnKey = (event) => { if (event.key === "Escape") { setOpen(false); triggerRef.current?.focus(); } };
    document.addEventListener("pointerdown", closeOnPointer);
    document.addEventListener("keydown", closeOnKey);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointer);
      document.removeEventListener("keydown", closeOnKey);
    };
  }, [open]);
  // Focus goes back to the trigger before the chosen action opens a dialog,
  // so the dialog can hand it back there when it closes.
  const choose = (action) => { setOpen(false); triggerRef.current?.focus(); action(); };
  const toggle = () => {
    if (open) { setOpen(false); return; }
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = 184;
    const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
    const estimatedHeight = 94;
    const top = rect.bottom + estimatedHeight > window.innerHeight ? Math.max(8, rect.top - estimatedHeight - 6) : rect.bottom + 6;
    setPosition({ top, left });
    setOpen(true);
  };
  return <>
    <button ref={triggerRef} className="item-menu-trigger" type="button" aria-label={`Tùy chọn ${label}`} aria-expanded={open} onClick={(event) => { event.stopPropagation(); toggle(); }}><Icon name="more" size={16} /></button>
    {open && createPortal(<div ref={menuRef} className="resource-menu-popover" role="menu" style={{ top: position.top, left: position.left }}>
      <button type="button" role="menuitem" onClick={() => choose(onRename)}><Icon name="edit" size={13} /> Đổi tên</button>
      <button type="button" role="menuitem" className="danger" onClick={() => choose(onDelete)}><Icon name="trash" size={13} /> Xóa</button>
    </div>, document.body)}
  </>;
}

// One dialog for confirmations: "rename-*" asks for a name, "delete-*" is
// destructive, anything else is a plain confirmation with its own wording.
// It is a form, so Enter confirms; Escape, Hủy and the backdrop cancel. When
// it closes, focus goes back to what had it when the dialog opened.
function ResourceDialog({ dialog, busy, onClose, onConfirm }) {
  const inputId = useId();
  const [value, setValue] = useState(dialog?.value ?? "");
  useEffect(() => setValue(dialog?.value ?? ""), [dialog?.kind, dialog?.value]);
  useEffect(() => {
    if (!dialog) return undefined;
    const onKey = (event) => { if (event.key === "Escape" && !busy) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [dialog, busy, onClose]);
  const returnFocus = dialog?.returnFocus;
  useEffect(() => {
    if (!returnFocus) return undefined;
    return () => { if (returnFocus.isConnected) returnFocus.focus(); };
  }, [returnFocus]);
  if (!dialog) return null;
  const isDelete = dialog.kind.startsWith("delete");
  const needsName = dialog.kind.startsWith("rename");
  const confirmLabel = dialog.confirmLabel ?? (isDelete ? "Xóa khỏi workspace" : "Lưu thay đổi");
  const submit = (event) => { event.preventDefault(); if (!busy && (!needsName || value.trim())) onConfirm(dialog, value.trim()); };
  return <div className="resource-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="resource-modal" role="dialog" aria-modal="true" aria-labelledby="resource-dialog-title" aria-describedby="resource-dialog-description" onSubmit={submit}>
      <div className={`resource-modal-icon ${isDelete ? "danger" : ""}`}><Icon name={dialog.icon ?? (isDelete ? "trash" : "edit")} size={19} /></div>
      <div><p className="dialog-kicker">{needsName ? "CHỈNH SỬA" : "XÁC NHẬN THAO TÁC"}</p><h2 id="resource-dialog-title">{dialog.title}</h2><p id="resource-dialog-description">{dialog.description}</p></div>
      {isDelete && <div className="dialog-warning">Thao tác này sẽ ẩn mục khỏi workspace. Dữ liệu nguồn được archive để bảo toàn lịch sử.</div>}
      {needsName && <div className="dialog-input-label"><label htmlFor={inputId}>Tên hiển thị</label><input id={inputId} autoFocus value={value} onChange={(event) => setValue(event.target.value)} maxLength={dialog.maxLength ?? 255} /></div>}
      {dialog.error && <p className="dialog-error" role="alert">{dialog.error}</p>}
      <div className="resource-modal-actions"><button type="button" className="dialog-secondary" onClick={onClose} disabled={busy}>Hủy</button><button type="submit" autoFocus={!needsName} className={isDelete ? "dialog-danger" : "dialog-primary"} disabled={busy || (needsName && !value.trim())}>{busy ? (dialog.busyLabel ?? "Đang lưu…") : confirmLabel}</button></div>
    </form>
  </div>;
}

function SessionBrowser({ sessions, filteredSessions, activeSession, activeDocument, booting, search, onSearch, busy, onSelectSession, onSelectDocument, onCreate, onUpload, onDialog, onNavigate }) {
  return <aside className="session-sidebar session-browser">
    <div className="sidebar-nav" aria-label="Điều hướng workspace"><button className="sidebar-nav-item active" type="button"><Icon name="grid" size={14} /><span>Workspace</span></button><button className="sidebar-nav-item" type="button" onClick={() => onNavigate?.("/app/library")}><Icon name="folder" size={14} /><span>Thư viện tài liệu</span><small>{sessions.reduce((count, session) => count + session.documents.length, 0)}</small></button></div>
    <div className="sidebar-divider"></div>
    <div className="session-heading"><div><small>WORKSPACE GẦN ĐÂY</small><h2>Phiên làm việc</h2></div><button className="session-create-button" aria-label="Tạo phiên làm việc mới" title="Tạo phiên làm việc mới" onClick={onCreate} disabled={busy}><Icon name="add" size={14} /><span>Tạo mới</span></button></div>
    <input className="session-search" aria-label="Tìm phiên hoặc tài liệu" value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Tìm phiên hoặc tài liệu…" />
    <div className="session-list">{booting && !sessions.length && <div className="session-loading" role="status">Đang tải workspace…</div>}{!booting && !filteredSessions.length && <div className="session-loading">Không tìm thấy phiên hoặc tài liệu phù hợp.</div>}{filteredSessions.map((session) => <section className={`session-item ${session.id === activeSession?.id ? "active" : ""}`} key={session.id}>
      <div className="session-row"><button className="session-button" title={session.title} onClick={() => onSelectSession(session)}><span className="session-icon"><Icon name="folder" size={14} /></span><span><b>{session.title}</b><small>{session.documents.length} tài liệu</small></span></button><ActionMenu label={session.title} onRename={() => onDialog({ kind: "rename-session", id: session.id, value: session.title, title: "Đổi tên phiên", description: "Tên này chỉ dùng để tổ chức workspace của bạn.", maxLength: 120 })} onDelete={() => onDialog({ kind: "delete-session", id: session.id, title: "Xóa phiên này?", description: `Phiên “${session.title}” và lịch sử hỏi đáp sẽ được archive.` })} /></div>
      {session.id === activeSession?.id && <div className="document-list"><div className="document-list-heading"><span>Tài liệu trong phiên</span><button type="button" className="session-upload-button" onClick={onUpload}><Icon name="upload" size={13} /> Thêm tài liệu</button></div>{session.documents.map((document) => <div className={`document-row ${document.id === activeDocument?.id ? "selected" : ""}`} key={document.id}><button className="document-button" title={document.file_name} onClick={() => onSelectDocument(document.id)}><span className="pdf-dot">PDF</span><span><b>{document.file_name}</b><small>{formatBytes(document.byte_size)} · {document.page_count ?? "?"} trang · {processingLabel(document.extraction_status)}</small></span></button><ActionMenu label={document.file_name} onRename={() => onDialog({ kind: "rename-document", id: document.id, value: document.file_name.slice(0, -4), title: "Đổi tên tài liệu", description: "PDF gốc và các citation không thay đổi.", maxLength: 251 })} onDelete={() => onDialog({ kind: "delete-document", id: document.id, title: "Xóa tài liệu này?", description: `Tài liệu “${document.file_name}” sẽ không còn hiện trong phiên.` })} /></div>)}{!session.documents.length && <button className="empty-document" onClick={onUpload}><Icon name="add" size={13} /> Thêm tài liệu đầu tiên</button>}</div>}</section>)}</div>
    <div className="sidebar-note"><b>Giới hạn tệp · 100 MiB</b></div>
  </aside>;
}

function App({ user = null, onSignOut = null, onNavigate }) {
  const { preference, resolvedTheme, setPreference } = useTheme();
  const [initialSessionSnapshot] = useState(readSessionSnapshot);
  const [sessions, setSessions] = useState(() => initialSessionSnapshot?.sessions ?? []);
  const [activeSessionId, setActiveSessionId] = useState(localStorage.getItem(SESSION_KEY));
  const [activeDocumentId, setActiveDocumentId] = useState(localStorage.getItem(DOCUMENT_KEY));
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(() => !initialSessionSnapshot?.sessions?.length);
  const [connectionState, setConnectionState] = useState("checking");
  // undefined until the first health answer; null when the server did not answer.
  const [runtimeHealth, setRuntimeHealth] = useState(undefined);
  const [bootError, setBootError] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState("info");
  const [search, setSearch] = useState("");
  const [citationPage, setCitationPage] = useState(null);
  const [citationQuote, setCitationQuote] = useState("");
  const [citationBbox, setCitationBbox] = useState(null);
  // Data rows of the active document: the drawer lists them and answer cards
  // use them to tell a user edit from the value read from the PDF.
  const [evidenceData, setEvidenceData] = useState(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [pendingMessages, setPendingMessages] = useState([]);
  const [activeJobs, setActiveJobs] = useState([]);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [requestMetrics, setRequestMetrics] = useState([]);
  const [performanceOpen, setPerformanceOpen] = useState(false);
  const [resourceDialog, setResourceDialog] = useState(null);
  const openDialog = useCallback((dialog) => setResourceDialog({ ...dialog, returnFocus: document.activeElement }), []);
  const uploadRef = useRef(null);
  const bootedRef = useRef(false);
  const refreshSequenceRef = useRef(0);
  const sessionRefreshSequenceRef = useRef(0);
  const uploadQueryConsumedRef = useRef(false);

  const showNotice = useCallback((message, kind = "info") => { setNotice(userFacingError(message)); setNoticeKind(kind); }, []);
  const clearNotice = useCallback(() => setNotice(""), []);
  // Errors stay until the user closes them; other notices are confirmations.
  useEffect(() => {
    if (!notice || noticeKind === "error") return undefined;
    const timer = window.setTimeout(clearNotice, NOTICE_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [notice, noticeKind, clearNotice]);

  useEffect(() => {
    const onRequest = (event) => setRequestMetrics((current) => [event.detail, ...current].slice(0, 40));
    window.addEventListener("sourcelens:request", onRequest);
    return () => window.removeEventListener("sourcelens:request", onRequest);
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer;
    const probe = async () => {
      try {
        const result = await request("/health");
        if (!disposed) setRuntimeHealth(result);
      } catch {
        if (!disposed) setRuntimeHealth(null);
      }
      if (!disposed) timer = window.setTimeout(probe, 30000);
    };
    probe();
    return () => { disposed = true; window.clearTimeout(timer); };
  }, []);

  const loadSessions = useCallback(async (preferredSession) => {
    const refreshSequence = ++refreshSequenceRef.current;
    const response = await request("/api/v1/sessions");
    let next = response.sessions ?? [];
    if (!next.length) {
      const created = await request("/api/v1/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "Phiên phân tích đầu tiên" }) });
      next = [created.session];
    }
    const fallbackSession = next.find((item) => item.documents?.length) ?? next[0];
    const selected = preferredSession && next.some((item) => item.id === preferredSession)
      ? preferredSession
      : (next.some((item) => item.id === activeSessionId) ? activeSessionId : fallbackSession.id);
    // The list endpoint intentionally returns metadata only (messages=[]).
    // Hydrate the selected session before replacing state, otherwise every
    // refresh removes chat history and stops polling accepted answer jobs.
    const detail = await request(`/api/v1/sessions/${selected}`);
    if (refreshSequence !== refreshSequenceRef.current) return;
    next = next.map((session) => session.id === selected ? detail.session : session);
    setSessions(next);
    writeSessionSnapshot(next);
    setConnectionState("online");
    setBootError("");
    if (selected !== activeSessionId) setActiveSessionId(selected);
  }, [activeSessionId]);

  // One list refresh at a time: a refresh that finds no session creates the
  // first one, so the next refresh must read the list after that create.
  // Mount (twice under StrictMode) and the session effect both refresh.
  const refresh = useCallback((preferredSession) => {
    const run = sessionListQueue.catch(() => {}).then(() => loadSessions(preferredSession));
    sessionListQueue = run;
    return run;
  }, [loadSessions]);

  const refreshSessionDetail = useCallback(async (sessionId) => {
    if (!sessionId) return false;
    const sequence = ++sessionRefreshSequenceRef.current;
    const detail = await request(`/api/v1/sessions/${sessionId}`);
    if (sequence !== sessionRefreshSequenceRef.current) return false;
    setSessions((current) => {
      const next = current.map((session) => session.id === sessionId ? detail.session : session);
      writeSessionSnapshot(next);
      return next;
    });
    return true;
  }, []);

  useEffect(() => {
    if (activeSessionId && !booting) refresh(activeSessionId).catch((error) => showNotice(error.message, "error"));
  }, [activeSessionId, booting, refresh, showNotice]);

  const refreshJobs = useCallback(async () => {
    try {
      const jobs = await request("/api/v1/jobs");
      // Queue failures/cancellation can happen outside the extraction function
      // (expired lease, worker crash). Reflect them instead of polling forever.
      setSessions((current) => current.map((session) => ({ ...session, documents: session.documents.map((document) => {
        if (document.extraction_status === "ready") return document;
        const job = (jobs.jobs ?? []).find((item) => item.kind === "extract_document" && item.payload?.document_id === document.id);
        const status = { queued: "queued", running: "processing", failed: "failed", cancelled: "failed" }[job?.status];
        return status ? { ...document, extraction_status: status, extraction_error: job.error_code ?? (job.status === "cancelled" ? "CANCELLED" : null) } : document;
      }) })));
      // Keep recent failures visible for retry, but never count completed or
      // cancelled work as an active job.  Previously the unfiltered list made
      // the header show a stale “đang xử lý” pill after the worker finished.
      setActiveJobs((jobs.jobs ?? []).filter((job) => ["queued", "running", "failed"].includes(job.status)));
    } catch {
      // Do not keep stale server data after a queue outage.  The workspace and
      // chat remain usable; the next poll will repopulate the Job Center.
      setActiveJobs([]);
    }
  }, []);

  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;
    refresh()
      .catch((error) => {
        setConnectionState("offline");
        setBootError(error.message);
        showNotice(error.message, "error");
      })
      .finally(() => setBooting(false));
  }, [refresh, showNotice]);
  useEffect(() => { if (activeSessionId) localStorage.setItem(SESSION_KEY, activeSessionId); }, [activeSessionId]);
  useEffect(() => { if (activeDocumentId) localStorage.setItem(DOCUMENT_KEY, activeDocumentId); }, [activeDocumentId]);

  const activeSession = sessions.find((item) => item.id === activeSessionId) ?? sessions[0];
  const activeDocument = activeSession?.documents.find((item) => item.id === activeDocumentId) ?? activeSession?.documents[0] ?? null;
  useEffect(() => {
    if (uploadQueryConsumedRef.current || !activeSession || new URLSearchParams(window.location.search).get("upload") !== "1") return;
    uploadQueryConsumedRef.current = true;
    window.setTimeout(() => uploadRef.current?.click(), 80);
  }, [activeSession?.id]);
  useEffect(() => { if (activeDocument && activeDocument.id !== activeDocumentId) setActiveDocumentId(activeDocument.id); }, [activeSession?.id, activeDocument?.id, activeDocumentId]);
  useEffect(() => { setEvidenceOpen(false); setCitationPage(null); setCitationQuote(""); setCitationBbox(null); }, [activeSession?.id, activeDocument?.id]);
  const evidencePath = activeSession && activeDocument ? `/api/v1/sessions/${activeSession.id}/documents/${activeDocument.id}` : null;
  const documentReady = activeDocument?.extraction_status === "ready";
  const loadEvidence = useCallback(async () => {
    if (!evidencePath || !documentReady) { setEvidenceData(null); return null; }
    const data = await request(`${evidencePath}/evidences`);
    setEvidenceData({ ...data, path: evidencePath });
    return data;
  }, [evidencePath, documentReady]);
  useEffect(() => { loadEvidence().catch(() => setEvidenceData(null)); }, [loadEvidence]);
  // Rows loaded for another document must never label this one.
  const activeEvidence = evidenceData?.path === evidencePath ? evidenceData : null;
  const evidenceByKey = useMemo(() => new Map((activeEvidence?.evidences ?? []).map((item) => [item.evidence_key, item])), [activeEvidence]);
  useEffect(() => {
    // The worker can expose both queued and processing. Stop polling only once
    // the document reaches a terminal state; otherwise the composer could stay
    // disabled forever after the first queue transition.
    if (!activeSession || !["queued", "processing"].includes(activeDocument?.extraction_status)) return undefined;
    let disposed = false;
    let timer;
    const poll = async () => {
      try { await refreshSessionDetail(activeSession.id); }
      catch (error) { if (!disposed) showNotice(error.message, "error"); }
      if (!disposed) timer = window.setTimeout(poll, 1500);
    };
    poll();
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [activeSession?.id, activeDocument?.id, activeDocument?.extraction_status, refreshSessionDetail, showNotice]);

  const filteredSessions = useMemo(() => sessions.filter((session) => session.title.toLowerCase().includes(search.toLowerCase()) || session.documents.some((document) => document.file_name.toLowerCase().includes(search.toLowerCase()))), [sessions, search]);
  const persistedMessages = (activeSession?.messages ?? []).filter((message) => !activeDocument || message.document_id === activeDocument.id);
  const pendingForActive = pendingMessages.filter((message) => message.session_id === activeSession?.id && message.document_id === activeDocument?.id);
  // A polling response can arrive before the POST handler's own refresh. Merge
  // by stable server ID so the accepted turn never vanishes or appears twice.
  const persistedIds = new Set(persistedMessages.map((message) => message.id));
  const messages = orderConversation(persistedMessages, pendingForActive.filter((message) => !persistedIds.has(message.id)));
  useEffect(() => {
    if (!persistedMessages.length) return;
    const persistedIds = new Set(persistedMessages.map((message) => message.id));
    setPendingMessages((current) => {
      const next = current.filter((message) => !persistedIds.has(message.id));
      return next.length === current.length ? current : next;
    });
  }, [activeSession?.id, activeDocument?.id, persistedMessages]);
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant" && !message.pending && !message.failed);
  const modeLabel = latestAssistant?.mode?.startsWith("ai:") ? "AI có dẫn nguồn" : "Dựa trên tài liệu";
  const answerProcessing = messages.some((message) => message.role === "assistant" && (message.status === "processing" || message.structured_answer?.presentation === "processing_v1"));
  useEffect(() => {
    refreshJobs();
    const hasActiveWork = ["queued", "processing"].includes(activeDocument?.extraction_status) || answerProcessing;
    const timer = window.setInterval(refreshJobs, hasActiveWork ? 5000 : 15000);
    return () => window.clearInterval(timer);
  }, [activeDocument?.extraction_status, answerProcessing, refreshJobs]);
  useEffect(() => {
    if (!activeSession || !answerProcessing) return undefined;
    let disposed = false;
    let timer;
    const poll = async () => {
      try { await refreshSessionDetail(activeSession.id); }
      catch (error) { if (!disposed) showNotice(error.message, "error"); }
      if (!disposed) timer = window.setTimeout(poll, 1200);
    };
    poll();
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [activeSession?.id, answerProcessing, refreshSessionDetail, showNotice]);
  const requestInFlightRef = useRef(false);
  const chatBodyRef = useRef(null);
  const chatViewRef = useRef({ scope: null, count: 0, answer: null });
  const [chatAnnouncement, setChatAnnouncement] = useState("");
  const chatScope = `${activeSession?.id}:${activeDocument?.id}`;
  const lastMessage = messages.at(-1);
  const lastAnswer = [...messages].reverse().find((message) => message.role === "assistant");
  const lastAnswerState = lastAnswer && !lastAnswer.pending && lastAnswer.status !== "processing" ? `${lastAnswer.id}:${lastAnswer.failed || lastAnswer.status === "failed" ? "failed" : "done"}` : null;

  // A conversation opens at its newest turn; a new question scrolls to the
  // bottom; a finished answer scrolls to its own first line.
  // Opening pins the view to the bottom while the turns finish laying out
  // (fonts, evidence rows, narrow screens wrapping later), until the user
  // scrolls or another rule moves the view.
  const pinnedRef = useRef(false);
  useLayoutEffect(() => {
    const node = chatBodyRef.current;
    const view = chatViewRef.current;
    if (!node) return;
    const opened = view.scope !== chatScope || (view.count === 0 && messages.length > 0);
    const previousAnswer = view.answer;
    Object.assign(view, { scope: chatScope, count: messages.length, answer: lastAnswerState });
    pinnedRef.current = opened;
    if (opened) { node.scrollTo({ top: node.scrollHeight, behavior: "instant" }); return; }
    if (lastAnswerState && lastAnswerState !== previousAnswer) {
      const article = node.querySelector(`[data-message-id="${CSS.escape(lastAnswer.id)}"]`);
      node.scrollTo({ top: Math.max(0, (article?.offsetTop ?? node.scrollHeight) - 12), behavior: "smooth" });
      setChatAnnouncement(lastAnswerState.endsWith("failed") ? "Chưa tạo được câu trả lời." : `Câu trả lời mới: ${presentationAnswer(lastAnswer)?.answer ?? lastAnswer.body ?? ""}`);
    } else if (lastMessage?.role === "user" || lastMessage?.pending) {
      node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
    }
  }, [chatScope, messages.length, lastMessage?.id, lastAnswerState]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const node = chatBodyRef.current;
    if (!node || typeof ResizeObserver !== "function") return undefined;
    const keepPinned = () => { if (pinnedRef.current) node.scrollTo({ top: node.scrollHeight, behavior: "instant" }); };
    const unpin = () => { pinnedRef.current = false; };
    const observer = new ResizeObserver(keepPinned);
    observer.observe(node);
    for (const child of node.children) observer.observe(child);
    const intents = ["wheel", "touchstart", "keydown", "pointerdown"];
    intents.forEach((name) => node.addEventListener(name, unpin, { passive: true }));
    return () => { observer.disconnect(); intents.forEach((name) => node.removeEventListener(name, unpin)); };
  }, [chatScope, messages.length]);

  async function createSession() {
    if (busy) return;
    setBusy(true);
    clearNotice();
    try {
      const created = await request("/api/v1/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: `Phiên phân tích ${sessions.length + 1}` }),
      });
      const createdSession = created.session;
      // Render the new session immediately. A slow list refresh must not make a
      // successful create operation look like a failed button click.
      setSessions((current) => {
        const next = [createdSession, ...current.filter((session) => session.id !== createdSession.id)];
        writeSessionSnapshot(next);
        return next;
      });
      setActiveSessionId(createdSession.id);
      setActiveDocumentId(null);
      setConnectionState("online");
      showNotice("Đã tạo phiên làm việc mới.");
      refresh(createdSession.id).catch((error) => showNotice(`Phiên đã được tạo nhưng danh sách chưa đồng bộ: ${userFacingError(error)}`, "error"));
    } catch (error) {
      showNotice(error, "error");
    } finally { setBusy(false); }
  }

  async function confirmResourceAction(dialog, value) {
    if (!dialog) return;
    setBusy(true);
    try {
      if (dialog.kind === "rename-session") {
        await request(`/api/v1/sessions/${dialog.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: value }) });
        setSessions((current) => { const next = current.map((session) => session.id === dialog.id ? { ...session, title: value } : session); writeSessionSnapshot(next); return next; });
        refresh(dialog.id).catch(() => {});
        showNotice("Đã đổi tên phiên.");
      } else if (dialog.kind === "delete-session") {
        await request(`/api/v1/sessions/${dialog.id}`, { method: "DELETE" });
        const remaining = sessions.filter((session) => session.id !== dialog.id);
        const nextId = remaining[0]?.id ?? null;
        setSessions(remaining); writeSessionSnapshot(remaining);
        setActiveSessionId(nextId);
        setActiveDocumentId(null);
        refresh(nextId).catch(() => {});
        showNotice("Đã đưa phiên vào lưu trữ.");
      } else if (dialog.kind === "rename-document" && activeSession) {
        await request(`/api/v1/sessions/${activeSession.id}/documents/${dialog.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_name: value }) });
        setSessions((current) => { const next = current.map((session) => session.id !== activeSession.id ? session : { ...session, documents: session.documents.map((document) => document.id === dialog.id ? { ...document, file_name: value.endsWith(".pdf") ? value : `${value}.pdf` } : document) }); writeSessionSnapshot(next); return next; });
        refresh(activeSession.id).catch(() => {});
        showNotice("Đã đổi tên tài liệu.");
      } else if (dialog.kind === "delete-document" && activeSession) {
        await request(`/api/v1/sessions/${activeSession.id}/documents/${dialog.id}`, { method: "DELETE" });
        setSessions((current) => { const next = current.map((session) => session.id !== activeSession.id ? session : { ...session, documents: session.documents.filter((document) => document.id !== dialog.id) }); writeSessionSnapshot(next); return next; });
        setActiveDocumentId(null);
        refresh(activeSession.id).catch(() => {});
        showNotice("Đã đưa tài liệu vào lưu trữ.");
      } else if (dialog.kind === "reextract-document" && activeSession) {
        await startReextraction(dialog.document);
      }
      setResourceDialog(null);
    } catch (error) {
      // The dialog stays open so the reason is next to the action that failed.
      setResourceDialog((current) => current && { ...current, error: userFacingError(error) });
    } finally { setBusy(false); }
  }

  async function retryBackend() {
    setBooting(true);
    setConnectionState("checking");
    setBootError("");
    clearNotice();
    try {
      await refresh();
    } catch (error) {
      setConnectionState("offline");
      setBootError(error.message);
    } finally {
      setBooting(false);
    }
  }

  async function handleJobAction(job, action) {
    setBusy(true);
    try {
      await request(`/api/v1/jobs/${job.id}/${action}`, { method: "POST" });
      await refresh(activeSession?.id);
      showNotice(action === "cancel" ? "Đã huỷ tác vụ." : "Đã đưa tác vụ vào hàng đợi thử lại.");
    } catch (error) { showNotice(error.message, "error"); }
    finally { setBusy(false); }
  }

  async function upload(file) {
    if (!file || !activeSession) return;
    if (file.size > 100 * 1024 * 1024) { showNotice("PDF vượt giới hạn 100 MiB.", "error"); return; }
    setBusy(true); showNotice("Đang tải lên và chuẩn bị tài liệu…");
    try {
      const form = new FormData(); form.append("file", file);
      const result = await request(`/api/v1/sessions/${activeSession.id}/documents`, { method: "POST", body: form });
      setSessions((current) => { const next = current.map((session) => session.id !== activeSession.id ? session : { ...session, documents: [...session.documents.filter((document) => document.id !== result.document.id), result.document], updated_at: new Date().toISOString() }); writeSessionSnapshot(next); return next; });
      setActiveDocumentId(result.document.id);
      refresh(activeSession.id).catch(() => {});
      showNotice(`Đã thêm ${result.document.file_name} (${formatBytes(result.document.byte_size)}). Bạn sẽ nhận được thông báo khi tài liệu sẵn sàng.`);
    } catch (error) { showNotice(error.message, "error"); } finally { setBusy(false); if (uploadRef.current) uploadRef.current.value = ""; }
  }

  // scope/idempotencyKey/after/replaces are set when re-sending a question
  // that was already sent once (a retry, or an unsaved question after a reload).
  async function submitQuestion(questionInput, { scope: givenScope, idempotencyKey = crypto.randomUUID(), after, replaces = [] } = {}) {
    const question = questionInput?.trim();
    const scope = givenScope ?? (activeSession && activeDocument ? { session_id: activeSession.id, document_id: activeDocument.id } : null);
    if (!question || !scope || requestInFlightRef.current || busy) return;
    const scopeDocument = sessions.find((session) => session.id === scope.session_id)?.documents.find((document) => document.id === scope.document_id);
    if (scopeDocument?.extraction_status === "failed") {
      showNotice(`Tài liệu chưa thể đọc nên chưa thể trả lời. ${canReextract ? "Bấm Trích xuất lại ở thanh trên PDF." : "Hãy thử xử lý lại tài liệu trong Trung tâm tác vụ."}`, "error");
      return;
    }
    requestInFlightRef.current = true;
    const unsaved = {
      id: crypto.randomUUID(), answer_id: crypto.randomUUID(), ...scope, question, key: idempotencyKey, sent_at: Date.now(),
      after: after !== undefined ? after : [...messages].reverse().find((message) => message.role === "user")?.id ?? null,
    };
    const userId = unsaved.id;
    const pendingId = unsaved.answer_id;
    setPendingMessages((current) => [...current.filter((message) => !replaces.includes(message.id)),
      { id: userId, role: "user", body: question, ...scope, after_question_id: unsaved.after, pending: true },
      { id: pendingId, role: "assistant", reply_to_message_id: userId, body: "", structured_answer: { pending: true }, ...scope, pending: true }]);
    if (!givenScope) setQuery("");
    setBusy(true);
    updateUnsavedQuestions((items) => [...items.filter((item) => !replaces.includes(item.id)), unsaved]);
    try {
      const result = await request(`/api/v1/sessions/${scope.session_id}/messages`, { method: "POST", body: JSON.stringify({ document_id: scope.document_id, question }), headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey } });
      if (result.job) setActiveJobs((current) => [result.job, ...current.filter((job) => job.id !== result.job.id)]);
      // The API has accepted the turn; show its durable message IDs now and
      // release the composer while the background answer job is still running.
      setPendingMessages((current) => current.map((message) => message.id === userId
        ? { ...result.user_message, ...scope, pending: false }
        : message.id === pendingId ? { ...result.assistant_message, ...scope, pending: false } : message));
      updateUnsavedQuestions((items) => items.filter((item) => item.id !== userId));
      requestInFlightRef.current = false;
      setBusy(false);
      const firstCitation = result.assistant_message?.citations?.[0];
      if (firstCitation?.page) { setCitationPage(firstCitation.page); setCitationQuote(firstCitation.quote ?? ""); setCitationBbox(normalizedBbox(firstCitation.bbox)); }
      try { await refreshSessionDetail(scope.session_id); }
      catch (refreshError) {
        showNotice(`Đã nhận câu trả lời nhưng chưa tải lại lịch sử: ${refreshError.message}`, "error");
      }
    } catch (error) {
      // The failed turn stays in the transcript, in its place and across a
      // reload, with its own retry; the error is shown there, not in a toast.
      // The retry reuses the key so a request that did finish on the server
      // is not answered twice.
      const failed = { ...unsaved, error: userFacingError(error) };
      updateUnsavedQuestions((items) => items.map((item) => item.id === userId ? failed : item));
      const [failedQuestion, failedAnswer] = failedTurn(failed);
      setPendingMessages((current) => current.map((message) => message.id === userId ? failedQuestion : message.id === pendingId ? failedAnswer : message));
    } finally { requestInFlightRef.current = false; setBusy(false); }
  }

  function retryAnswer(message) {
    if (message.retry) {
      const { question, ...options } = message.retry;
      submitQuestion(question, options);
      return;
    }
    // A failed answer saved by the server: ask its question again.
    const question = messages.find((item) => item.id === message.reply_to_message_id);
    if (question?.role === "user") submitQuestion(question.body);
  }

  // After a reload, bring back the questions the server has not saved: send
  // a young one that was still being sent again, show the others as failed.
  const resumedRef = useRef(false);
  useEffect(() => {
    if (resumedRef.current || booting || !sessions.length) return;
    resumedRef.current = true;
    const known = (item) => sessions.some((session) => session.id === item.session_id && session.documents.some((document) => document.id === item.document_id));
    const items = readUnsavedQuestions().filter(known);
    updateUnsavedQuestions(() => items);
    const resend = items.find((item) => !item.error && Date.now() - Number(item.sent_at) < RESEND_AFTER_RELOAD_MS);
    const failed = items.filter((item) => item !== resend).map((item) => item.error ? item : { ...item, error: "Câu hỏi chưa được gửi xong trước khi tải lại trang. Hãy thử lại." });
    updateUnsavedQuestions((current) => current.map((item) => failed.find((entry) => entry.id === item.id) ?? item));
    if (failed.length) setPendingMessages((current) => [...current, ...failed.flatMap(failedTurn)]);
    if (resend) submitQuestion(resend.question, { scope: { session_id: resend.session_id, document_id: resend.document_id }, idempotencyKey: resend.key, after: resend.after ?? null, replaces: [resend.id] });
  }, [booting, sessions]); // eslint-disable-line react-hooks/exhaustive-deps

  async function ask(event) { event.preventDefault(); await submitQuestion(query); }

  async function stopAnswer(message) {
    let job = activeJobs.find((item) => item.kind === "answer_question" && item.payload?.assistant_message_id === message.id && ["queued", "running"].includes(item.status));
    try {
      if (!job) {
        const result = await request("/api/v1/jobs");
        job = (result.jobs ?? []).find((item) => item.kind === "answer_question" && item.payload?.assistant_message_id === message.id && ["queued", "running"].includes(item.status));
      }
      if (!job) { showNotice("Không tìm thấy tác vụ đang chạy. Đang cập nhật cuộc trò chuyện."); await refreshSessionDetail(activeSession.id); return; }
      await request(`/api/v1/jobs/${job.id}/cancel`, { method: "POST" });
      await Promise.all([refreshSessionDetail(activeSession.id), refreshJobs()]);
      showNotice("Đã dừng tạo câu trả lời.");
    } catch (error) { showNotice(error.message, "error"); }
  }

  const closeEvidence = useCallback(() => setEvidenceOpen(false), []);

  // Shows a cited place in the PDF. On narrow screens the reader sits above
  // the chat, so bring it into view when it is off screen.
  const readerRef = useRef(null);
  function openCitation(page, quote = "", bbox = null) {
    setCitationPage(page); setCitationQuote(quote ?? ""); setCitationBbox(normalizedBbox(bbox));
    bringIntoView(readerRef.current);
  }

  // The number panel opens over the chat, which sits below the reader on
  // narrow screens.
  const chatColumnRef = useRef(null);
  async function openEvidence() {
    if (!documentReady) return;
    setEvidenceOpen(true);
    bringIntoView(chatColumnRef.current);
    try { await loadEvidence(); }
    catch (error) { setEvidenceOpen(false); showNotice(error.message, "error"); }
  }

  async function evidenceSaved(evidence, result) {
    const before = formatNumber(result.revision?.old_numeric_value ?? evidence.current_numeric_value) || "chưa có số";
    const after = formatNumber(result.revision?.numeric_value);
    showNotice(`Đã lưu ${before} → ${after}.${result.affected_message_ids?.length ? " Các câu trả lời dùng số này cần được tính lại." : ""}`);
    try { await Promise.all([loadEvidence(), refreshSessionDetail(activeSession.id)]); }
    catch (error) { showNotice(error.message, "error"); }
  }

  // The server says whether it can re-read a document (not with PostgreSQL,
  // where a failed document is retried from the job center instead).
  const canReextract = runtimeHealth?.capabilities?.reextraction?.status === "available";

  function reextractDocument(document) {
    openDialog({
      kind: "reextract-document", document, icon: "refresh", confirmLabel: "Đọc lại tài liệu", busyLabel: "Đang gửi yêu cầu…",
      title: "Đọc lại tài liệu này?",
      description: document.extraction_status === "ready"
        ? `SourceLens sẽ đọc lại “${document.file_name}” và lập lại toàn bộ bảng số liệu. Một số bạn đã sửa chỉ được giữ khi số đó vẫn ở cùng vị trí và in giống hệt trong PDF. Khi đọc xong, chỉ câu trả lời dùng số đã thay đổi mới được đánh dấu cần cập nhật. Việc này có thể mất vài phút.`
        : `SourceLens sẽ thử đọc lại “${document.file_name}”. Việc này có thể mất vài phút.`,
    });
  }

  // Documents being re-read, so the end of the run can be announced.
  const reextractingRef = useRef(new Set());
  async function startReextraction(document) {
    // Which answers to flag is known only once the new reading is ready.
    await request(`/api/v1/sessions/${activeSession.id}/documents/${document.id}/extraction`, { method: "POST" });
    reextractingRef.current.add(document.id);
    showNotice(`Đang đọc lại ${document.file_name}…`);
    await refreshSessionDetail(activeSession.id).catch(() => {});
  }
  useEffect(() => {
    const id = activeDocument?.id;
    const status = activeDocument?.extraction_status;
    if (!id || !reextractingRef.current.has(id) || !["ready", "failed"].includes(status)) return;
    reextractingRef.current.delete(id);
    if (status === "ready") showNotice(rereadSummary(activeDocument));
    else {
      const kept = activeDocument.pending_edits?.length ?? 0;
      showNotice(`Chưa đọc lại được ${activeDocument.file_name}. Hãy thử lại sau.${kept ? ` ${kept} số bạn đã sửa vẫn được giữ cho lần đọc sau.` : ""}`, "error");
    }
  }, [activeDocument, showNotice]);

  const nextTheme = preference === "light" ? "dark" : preference === "dark" ? "system" : "light";
  const nextThemeLabel = { light: "giao diện sáng", dark: "giao diện tối", system: "giao diện theo hệ thống" }[nextTheme];
  const activeJobCount = activeJobs.filter((job) => ["queued", "running"].includes(job.status)).length;
  const readinessState = runtimeHealth === null ? "offline" : runtimeHealth?.readiness?.status ?? "checking";
  const readinessLabel = readinessState === "ready" ? "Sẵn sàng" : readinessState === "degraded" ? "Một số dịch vụ cần kiểm tra" : readinessState === "checking" ? "Đang kiểm tra" : "Kết nối gián đoạn";
  const readinessBlockers = runtimeHealth?.readiness?.blockers?.length ? "Một số dịch vụ chưa sẵn sàng" : "";

  if (!booting && connectionState === "offline" && !sessions.length) {
    return <div className="app-shell connection-shell">
      <a className="skip-link" href="#main-content">Bỏ qua điều hướng</a>
      <header className="topbar">
        <div className="brand"><span>S</span><div><strong>SourceLens</strong><small>Document intelligence</small></div></div>
        <div className="top-actions"><span className="connection-pill offline"><i></i>Mất kết nối</span></div>
      </header>
      <main className="connection-screen" id="main-content">
        <section className="connection-card" role="alert">
          <div className="connection-icon"><Icon name="trace" size={24} /></div>
          <span className="eyebrow">KẾT NỐI HỆ THỐNG</span>
          <h1>Backend chưa sẵn sàng</h1>
          <p>{bootError ? userFacingError(bootError) : "Không thể tải workspace lúc này. Bạn có thể thử kết nối lại."}</p>
          <button onClick={retryBackend}><Icon name="refresh" size={15} /> Thử kết nối lại</button>
        </section>
      </main>
    </div>;
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Bỏ qua điều hướng</a>
    <a className="skip-link" href="#chat-question">Đến ô đặt câu hỏi</a>
    <header className="topbar">
      <div className="brand"><span>S</span><div><strong>SourceLens</strong><small>Document intelligence</small></div></div>
      <div className="topbar-context"><span>WORKSPACE</span><strong>{activeDocument?.file_name ?? "Thư viện tài liệu"}</strong></div>
      <nav className="top-nav" aria-label="Điều hướng chính"><button className="top-nav-item active" type="button" aria-current="page"><Icon name="grid" size={14} /> Workspace</button><button className="top-nav-item" type="button" onClick={() => onNavigate?.("/app/library")}><Icon name="folder" size={14} /> Tài liệu</button></nav>
      <div className="top-actions">
        <span className={`connection-pill ${readinessState === "ready" ? "online" : readinessState === "offline" ? "offline" : "checking"}`} title={readinessBlockers || readinessLabel}><i></i>{readinessLabel}</span>
        {activeJobs.length > 0 && <button className="job-pill" type="button" aria-label={`Mở trung tâm tác vụ, ${activeJobs.length} tác vụ`} onClick={() => setJobsOpen(true)}><i></i>{activeJobCount > 0 ? `${activeJobCount} đang xử lý` : "Trung tâm tác vụ"}</button>}
        <button className="icon-button" type="button" title={`Chuyển sang ${nextThemeLabel}`} aria-label={`Chuyển sang ${nextThemeLabel}`} onClick={() => setPreference(nextTheme)}><Icon name={resolvedTheme === "dark" ? "moon" : "sun"} size={15} /></button>
        <button className="audit-button" title="Mở bảng số liệu của tài liệu" disabled={!documentReady} onClick={openEvidence}><Icon name="link" size={14} /><span className="audit-button-label">Bằng chứng</span></button>
        <ProfileMenu user={user} onSignOut={onSignOut} onNavigate={onNavigate} />
        <input ref={uploadRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => upload(event.target.files?.[0])} />
      </div>
    </header>
    <main className="workspace" id="main-content">
      <SessionBrowser sessions={sessions} filteredSessions={filteredSessions} activeSession={activeSession} activeDocument={activeDocument} booting={booting} search={search} onSearch={setSearch} busy={busy} onSelectSession={(session) => { setActiveSessionId(session.id); setActiveDocumentId(session.documents[0]?.id ?? null); }} onSelectDocument={setActiveDocumentId} onCreate={createSession} onUpload={() => uploadRef.current?.click()} onDialog={openDialog} onNavigate={onNavigate} />
      <section className="reader-column" ref={readerRef}><PdfViewer document={activeDocument} sessionId={activeSession?.id} citationPage={citationPage} evidenceQuote={citationQuote} evidenceBbox={citationBbox} onReextract={canReextract ? reextractDocument : undefined} reextractDisabled={busy} />{notice && <div className={`toast ${noticeKind}`} role={noticeKind === "error" ? "alert" : "status"}><span>{notice}</span><button type="button" className="toast-close" aria-label="Đóng thông báo" onClick={clearNotice}><Icon name="close" size={13} /></button></div>}</section>
      <aside className="chat-column" ref={chatColumnRef}>
        <header className="chat-header"><div className="ai-avatar">S</div><div><h2>Trợ lý tài liệu</h2><span>{activeDocument ? activeDocument.file_name : "Chưa chọn tài liệu"}</span></div><span className="mode-badge">{modeLabel}</span></header>
        <div className="chat-body" ref={chatBodyRef}>
          <p className="visually-hidden" aria-live="polite">{chatAnnouncement}</p>
          {!messages.length && <div className="welcome"><div className="welcome-mark"><Icon name="spark" size={18} /></div><h3>Bắt đầu với tài liệu của bạn</h3><p>Đặt câu hỏi để nhận câu trả lời có dẫn nguồn, trích dẫn theo trang và cấu trúc rõ ràng.</p>{activeDocument?.extraction_status === "ready" && <button onClick={() => setQuery("Tóm tắt nội dung chính của tài liệu")}>Tóm tắt tài liệu</button>}</div>}
          {messages.map((message) => <ChatMessage key={message.id} message={message} busy={busy} evidenceByKey={evidenceByKey} onCitation={openCitation} onStop={stopAnswer} onRetry={retryAnswer} onAsk={submitQuestion} onEditQuestion={(text) => { setQuery(text); document.getElementById("chat-question")?.focus(); }} onCopy={async (text) => { try { await navigator.clipboard.writeText(text); showNotice("Đã sao chép."); } catch { showNotice("Không thể sao chép.", "error"); } }} />)}
        </div>
        <form className="chat-composer" onSubmit={ask}><textarea id="chat-question" aria-label="Câu hỏi về tài liệu" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={!activeDocument ? "Thêm tài liệu để bắt đầu" : activeDocument.extraction_status === "ready" ? "Đặt câu hỏi về tài liệu…" : activeDocument.extraction_status === "failed" ? canReextract ? "Chưa thể đọc tài liệu, bấm Trích xuất lại" : "Chưa thể đọc tài liệu — mở Trung tâm tác vụ để thử lại" : "Đặt câu hỏi — trợ lý sẽ trả lời khi tài liệu sẵn sàng…"} disabled={!activeDocument || busy} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} /><div><span>{activeDocument?.extraction_status === "ready" ? "Trợ lý sẵn sàng" : activeDocument?.extraction_status === "failed" ? "Tài liệu chưa đọc được" : activeDocument?.extraction_status === "queued" || activeDocument?.extraction_status === "processing" ? "Câu hỏi sẽ được xử lý sau khi đọc tài liệu" : "Chưa sẵn sàng"}</span><button aria-label="Gửi câu hỏi" title="Gửi câu hỏi" disabled={!activeDocument || activeDocument.extraction_status === "failed" || busy || !query.trim()}><Icon name="send" size={15} /></button></div></form>
        <EvidenceDrawer data={evidenceOpen ? activeEvidence : null} basePath={evidencePath} onClose={closeEvidence} onReload={() => loadEvidence().catch(() => {})} onSaved={evidenceSaved} onFocus={(evidence) => openCitation(evidence.page_number, "", evidence.bbox)} />
      </aside>
      <ResourceDialog dialog={resourceDialog} busy={busy} onClose={() => setResourceDialog(null)} onConfirm={confirmResourceAction} />
      <JobCenterDrawer jobs={jobsOpen ? activeJobs : null} busy={busy} onClose={() => setJobsOpen(false)} onAction={handleJobAction} />
    </main>
  </div>;
}

export default App;
