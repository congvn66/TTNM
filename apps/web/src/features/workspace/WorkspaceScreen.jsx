import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { API, request } from "../../shared/api/client.js";
import { useTheme } from "../theme/ThemeProvider.jsx";
import { EvidenceList, ScriptCard } from "./ToolAnswer.jsx";

const SESSION_KEY = "sourcelens-active-session";
const DOCUMENT_KEY = "sourcelens-active-document";
const SESSION_SNAPSHOT_KEY = "sourcelens-session-snapshot-v1";
const SESSION_SNAPSHOT_TTL_MS = 60_000;
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

function Icon({ name, size = 16 }) {
  const paths = {
    add: <path d="M12 5v14M5 12h14" />,
    arrowLeft: <><path d="m15 18-6-6 6-6" /><path d="M9 12h10" /></>,
    arrowRight: <><path d="m9 18 6-6-6-6" /><path d="M5 12h10" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    chevronDown: <path d="m6 9 6 6 6-6" />,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></>,
    fit: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
    folder: <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h4l2 2h7A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z" />,
    grid: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
    link: <><path d="M10 13a5 5 0 0 0 7.1.1l1.4-1.4a5 5 0 0 0-7.1-7.1L10 6" /><path d="M14 11a5 5 0 0 0-7.1-.1l-1.4 1.4a5 5 0 0 0 7.1 7.1L14 18" /></>,
    more: <><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></>,
    edit: <><path d="m4 20 4.2-1 10-10a2.1 2.1 0 0 0-3-3l-10 10z" /><path d="m13.8 7.2 3 3" /></>,
    trash: <><path d="M4 7h16M10 11v5M14 11v5M6 7l1 13h10l1-13M9 7V4h6v3" /></>,
    user: <><circle cx="12" cy="8" r="3.2" /><path d="M5 20c.6-3.4 3-5.2 7-5.2s6.4 1.8 7 5.2" /></>,
    logout: <><path d="M10 5H5v14h5" /><path d="m14 8 4 4-4 4M8 12h10" /></>,
    moon: <path d="M20.5 15.2A8.5 8.5 0 0 1 8.8 3.5 8.5 8.5 0 1 0 20.5 15.2Z" />,
    minus: <path d="M5 12h14" />,
    plus: <path d="M12 5v14M5 12h14" />,
    refresh: <><path d="M20 11a8 8 0 0 0-14.7-3L4 10" /><path d="M4 5v5h5" /><path d="M4 13a8 8 0 0 0 14.7 3L20 14" /><path d="M20 19v-5h-5" /></>,
    rotate: <><path d="M4 9a8 8 0 0 1 13.7-3L20 8" /><path d="M20 3v5h-5" /><path d="M20 15a8 8 0 0 1-13.7 3L4 16" /><path d="M4 21v-5h5" /></>,
    send: <><path d="m4 4 16 8-16 8 3-8z" /><path d="M7 12h13" /></>,
    settings: <><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" /><circle cx="12" cy="12" r="3.5" /></>,
    spark: <><path d="m12 3 1.3 5.7L19 10l-5.7 1.3L12 17l-1.3-5.7L5 10l5.7-1.3z" /><path d="m19 16 .6 2.4L22 19l-2.4.6z" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" /></>,
    trace: <><path d="M5 5h4v4H5zM15 15h4v4h-4z" /><path d="M9 7h3a3 3 0 0 1 3 3v5" /><path d="M12 15h3" /></>,
    upload: <><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M5 20h14" /></>,
  };
  return <svg className="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
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

const ERROR_COPY = {
  AUTH_REQUIRED: "Phiên đăng nhập đã hết. Vui lòng đăng nhập lại.",
  SESSION_TITLE_REQUIRED: "Hãy nhập tên cho phiên làm việc.",
  SESSION_NOT_FOUND: "Không tìm thấy phiên làm việc này. Hãy tải lại danh sách.",
  DOCUMENT_NOT_FOUND: "Không tìm thấy tài liệu này. Hãy tải lại danh sách.",
  DATABASE_UNAVAILABLE: "Dịch vụ dữ liệu tạm thời không sẵn sàng. Hãy thử lại sau.",
  INVALID_PDF: "Tệp không phải PDF hợp lệ hoặc không thể đọc được.",
  PDF_ENCRYPTED: "PDF này được đặt mật khẩu nên không đọc được. Hãy gỡ mật khẩu rồi tải lên lại.",
  PDF_TOO_LARGE: "Tệp PDF vượt quá giới hạn 100 MiB.",
  PDF_TOO_MANY_PAGES: "Tài liệu vượt quá số trang cho phép.",
  EXTRACTION_NOT_READY: "Tài liệu đang được chuẩn bị. Bạn có thể đặt câu hỏi khi tài liệu sẵn sàng.",
  AI_PROVIDER_TIMEOUT: "AI phản hồi quá lâu. Bạn có thể thử gửi lại câu hỏi.",
  AI_PROVIDER_UNAVAILABLE: "Không kết nối được tới dịch vụ AI. Kiểm tra mạng hoặc thử lại sau.",
  AI_MODEL_UNAVAILABLE: "Mô hình AI hiện không khả dụng. Kiểm tra lại cấu hình model.",
  AI_PROVIDER_HTTP_ERROR: "Dịch vụ AI từ chối yêu cầu. Kiểm tra API key và giới hạn sử dụng.",
  AI_NOT_CONFIGURED: "Chưa cấu hình nhà cung cấp AI cho môi trường này.",
  AI_INVALID_OUTPUT: "AI trả về dữ liệu không đúng định dạng. Hãy thử lại câu hỏi.",
  AI_UNGROUNDED_CITATION: "AI trả về trích dẫn không nằm trong tài liệu. Hãy thử lại câu hỏi.",
  AI_UNSUPPORTED_EVIDENCE: "AI chưa xác minh được evidence trong tài liệu. Hãy thử lại câu hỏi.",
  DOCUMENT_CONTEXT_TOO_LARGE: "Tài liệu quá dài để trợ lý đọc hết trong một lần hỏi.",
  ASSISTANT_INCOMPLETE: "Trợ lý chưa hoàn tất câu trả lời trong số bước cho phép. Hãy thử lại hoặc hỏi cụ thể hơn.",
  QUEUE_UNAVAILABLE: "Hàng đợi xử lý chưa sẵn sàng. Hãy khởi động worker hoặc thử lại sau.",
};

function userFacingError(value) {
  const raw = typeof value === "string" ? value : value?.message;
  if (!raw) return "Không thể hoàn tất thao tác. Hãy thử lại.";
  const code = Object.keys(ERROR_COPY).find((key) => raw.includes(key));
  if (code) return ERROR_COPY[code];
  if (raw.includes("Không kết nối được tới backend")) return "Không thể kết nối tới máy chủ. Hãy thử lại sau ít phút.";
  if (raw.includes("Yêu cầu quá thời gian chờ")) return "Máy chủ phản hồi quá lâu. Hãy thử lại sau ít phút.";
  return raw.replace(/^\w+_[A-Z_]+:\s*/, "").trim();
}

function normalizedBbox(value) {
  const raw = Array.isArray(value) ? value : [value?.x0, value?.y0, value?.x1, value?.y1];
  if (raw.length !== 4 || raw.some((item) => !Number.isFinite(Number(item)))) return null;
  const [x0, y0, x1, y1] = raw.map((item) => Math.max(0, Math.min(1, Number(item))));
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

// PDF.js represents affine transforms as [a, b, c, d, e, f]. Keeping this
// tiny operation local avoids pulling the whole PDF.js runtime into the
// initial bundle just to derive a citation box from the already-rendered text.
function multiplyTransform(first, second) {
  return [
    first[0] * second[0] + first[2] * second[1],
    first[1] * second[0] + first[3] * second[1],
    first[0] * second[2] + first[2] * second[3],
    first[1] * second[2] + first[3] * second[3],
    first[0] * second[4] + first[2] * second[5] + first[4],
    first[1] * second[4] + first[3] * second[5] + first[5],
  ];
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
    <div className="job-center-list">{jobs.length ? jobs.map((job) => <article className="job-center-row" key={job.id}><div className={`job-center-status ${job.status}`}><span></span></div><div className="job-center-main"><strong>{["document_extraction", "extract_document"].includes(job.kind) ? "Chuẩn bị tài liệu" : ["answer_generation", "generate_answer"].includes(job.kind) ? "Tạo câu trả lời" : "Tác vụ đang chạy"}</strong><small>{job.status === "queued" ? "Đang chờ xử lý" : job.status === "running" ? "Đang xử lý" : job.status === "failed" ? "Cần thử lại" : "Đã hoàn tất"}{job.error_code ? ` · ${job.error_code}` : ""}</small></div><div className="job-center-actions">{["queued", "running"].includes(job.status) && <button type="button" onClick={() => onAction(job, "cancel")} disabled={busy}>Huỷ</button>}{job.status === "failed" && <button type="button" onClick={() => onAction(job, "retry")} disabled={busy}>Thử lại</button>}</div></article>) : <div className="job-center-empty"><span>✓</span><p>Không có tác vụ gần đây.</p><small>Khi tải PDF hoặc hỏi AI, trạng thái sẽ xuất hiện ở đây.</small></div>}</div>
  </section>;
}

// What the number is: table row and column, or chart category and series.
function evidenceName(evidence) {
  const { row_header: row, column_header: column } = evidence.table_locator ?? {};
  const { category_label: category, series_label: series } = evidence.chart_read ?? {};
  return [row, column, category, series].filter(Boolean).join(" · ");
}

function EvidenceDrawer({ data, busy, onClose, onFocus, onSave }) {
  const [editingKey, setEditingKey] = useState(null);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  if (!data) return null;
  const beginEdit = (evidence) => { setEditingKey(evidence.evidence_key); setValue(evidence.current_numeric_value ?? ""); setReason(""); };
  return <section className="evidence-drawer" role="dialog" aria-label="Dữ liệu số và lịch sử sửa">
    <header className="audit-drawer-header"><div><span className="audit-kicker">DATA REVISION</span><h3>Dữ liệu đầu vào</h3><small>revision {data.data_revision ?? 0} · giá trị gốc không bị ghi đè</small></div><button aria-label="Đóng dữ liệu" onClick={onClose}><Icon name="close" size={15} /></button></header>
    <div className="evidence-drawer-body">{data.evidences?.length ? data.evidences.map((evidence) => <article className="evidence-record" key={evidence.evidence_key}>
      <button className="evidence-record-main" onClick={() => onFocus(evidence)}><span>p.{evidence.page_number} · {evidence.method_label}</span><b>{evidence.current_numeric_value ?? evidence.raw_text ?? "Chưa đọc được"}</b>{evidenceName(evidence) && <small>{evidenceName(evidence)}</small>}<small>Gốc: {evidence.original_numeric_value ?? evidence.raw_text ?? "chưa xác định"} · {evidence.revision_count} revision{evidence.data_status && evidence.data_status !== "valid" ? " · Cần kiểm tra" : ""}</small><code>{evidence.evidence_key}</code></button>
      {editingKey === evidence.evidence_key ? <form className="evidence-edit-form" onSubmit={(event) => { event.preventDefault(); onSave(evidence, value, reason).then(() => setEditingKey(null)).catch(() => {}); }}><label>Giá trị mới<input autoFocus value={value} onChange={(event) => setValue(event.target.value)} required /></label><label>Lý do sửa<textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength="3" required placeholder="Ví dụ: Đối chiếu lại PDF gốc" /></label><div><button type="button" onClick={() => setEditingKey(null)}>Hủy</button><button type="submit" disabled={busy}>Lưu revision</button></div></form> : <button className="evidence-edit-button" onClick={() => beginEdit(evidence)} disabled={busy}>Sửa số</button>}
    </article>) : <p className="evidence-empty">Chưa có số liệu trích xuất để sửa.</p>}</div>
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

function StructuredAnswer({ answer, fallback, onCitation }) {
  if (answer?.pending) return <div className="typing-indicator" aria-live="polite"><span className="typing-dots"><i></i><i></i><i></i></span><span>Đang tạo câu trả lời</span></div>;
  if (!answer && typeof fallback === "string" && fallback.startsWith("Không thể tạo câu trả lời:")) return <div className="answer-failure" role="alert"><Icon name="refresh" size={14} /><span>{fallback}</span></div>;
  if (!answer) return <p>{fallback}</p>;
  if (answer.presentation === "retrieval_excerpt") return <div className="structured-answer retrieval-answer">
    <p className="answer-lead">{answer.answer}</p>
    {answer.summary && <p className="answer-summary">{answer.summary}</p>}
    <RetrievalExcerpt answer={answer} />
    {answer.warnings?.filter(Boolean).length > 0 && <div className="answer-status-note"><Icon name="trace" size={13} /><span>{answer.warnings.filter(Boolean)[0]}</span></div>}
  </div>;
  const warnings = answer.warnings?.filter(Boolean) ?? [];
  return <div className="structured-answer">
    <p className="answer-lead">{answer.answer}</p>
    {answer.evidence?.length > 0 && <EvidenceList items={answer.evidence} onCitation={onCitation} />}
    {answer.summary && <p className="answer-summary">{answer.summary}</p>}
    {answer.claims?.length > 0 && <section className="answer-section answer-claims"><h4>Claims và căn cứ</h4>{answer.claims.map((claim, index) => <div className="claim-card" key={`${claim.claim}-${index}`}>
      <p>{claim.claim}</p>
      {claim.evidence_quotes?.map((quote, quoteIndex) => <button className="evidence-quote" key={`${quote}-${quoteIndex}`} onClick={() => onCitation?.(claim.evidence_pages?.[quoteIndex] ?? claim.evidence_pages?.[0], quote)}><span className="evidence-quote-label"><Icon name="link" size={12} /> Evidence</span><span>“{quote}”</span></button>)}
      {claim.evidence_pages?.length > 0 && <div className="evidence-pages">{claim.evidence_pages.map((page) => <button className="citation" key={page} onClick={() => onCitation?.(page, claim.evidence_quotes?.[0] ?? "")}><Icon name="link" size={12} /> Trang {page}</button>)}</div>}
    </div>)}</section>}
    {answer.sections?.map((section, index) => <section className="answer-section" key={`${section.heading}-${index}`}><h4>{section.heading}</h4>{section.points?.filter(Boolean).length > 0 && <ul>{section.points.filter(Boolean).map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}</ul>}</section>)}
    {answer.formulas?.length > 0 && <section className="answer-section"><h4>Công thức và tính toán</h4>{answer.formulas.map((formula, index) => formula.inputs ? <ScriptCard formula={formula} onCitation={onCitation} key={`script-${index}`} /> : <div className="formula-card" key={`${formula.name}-${index}`}><strong>{formula.name}</strong><code>{formula.expression}</code><span>Thay số: {formula.substitution || "Chưa đủ toán hạng"}</span><b>Kết quả: {formula.result ?? "Không xác định"}{formula.unit ? ` ${formula.unit}` : ""}</b>{["verified", "succeeded"].includes(formula.calculation?.status) ? <em className="formula-verified">✓ Calculator: {formula.calculation.computed_result} {formula.calculation.unit}</em> : <em className="formula-unverified">Calculator: {formula.calculation?.status ?? "chưa chạy"}</em>}</div>)}</section>}
    {answer.tables?.map((table, index) => <section className="answer-section" key={`${table.title}-${index}`}><h4>{table.title}</h4><div className="answer-table-wrap"><table className="answer-table"><thead><tr>{table.columns?.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{table.rows?.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div></section>)}
    {warnings.length > 0 && <div className="answer-warnings"><strong>Lưu ý</strong><ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
  </div>;
}

function PdfViewer({ document, sessionId, citationPage, evidenceQuote, evidenceBbox, onReextract, reextractDisabled }) {
  const viewportRef = useRef(null);
  const canvasRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [pdf, setPdf] = useState(null);
  const [page, setPage] = useState(1);
  const [scale, setScale] = useState(1.05);
  const [rotation, setRotation] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [textItems, setTextItems] = useState([]);
  const [textViewport, setTextViewport] = useState(null);
  const [citationQuote, setCitationQuote] = useState("");
  const [citationBbox, setCitationBbox] = useState(null);
  const dragRef = useRef(null);

  useEffect(() => {
    let disposed = false;
    setPdf(null); setPage(1); setError(""); setTextItems([]); setTextViewport(null); setCitationQuote(""); setCitationBbox(null);
    if (!document) { setLoading(false); return undefined; }
    const relativeFileUrl = document.file_url || `/api/v1/sessions/${sessionId}/documents/${document.id}/file`;
    let fileUrl;
    try { fileUrl = new URL(relativeFileUrl, API).toString(); } catch { fileUrl = ""; }
    if (!relativeFileUrl || relativeFileUrl.includes("undefined") || !/^https?:/.test(fileUrl)) {
      setLoading(false); setError("Thiếu URL file PDF của tài liệu này"); return undefined;
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
    }).catch((reason) => {
      if (!disposed) { setError(reason?.message || "Không thể đọc PDF"); setLoading(false); }
    });
    return () => { disposed = true; task?.destroy(); };
  }, [document?.id, document?.file_url, sessionId]);

  useEffect(() => {
    if (!pdf || !canvasRef.current) return undefined;
    let cancelled = false;
    pdf.getPage(page).then((pdfPage) => {
      if (cancelled) return;
      const viewport = pdfPage.getViewport({ scale, rotation });
      const canvas = canvasRef.current;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      setTextViewport({ width: viewport.width, height: viewport.height, transform: viewport.transform, rotation, scale });
      if (rotation === 0) pdfPage.getTextContent().then((content) => setTextItems(content.items.filter((item) => item.str?.trim()))).catch(() => setTextItems([]));
      else setTextItems([]);
      const context = canvas.getContext("2d");
      renderTaskRef.current?.cancel();
      renderTaskRef.current = pdfPage.render({ canvasContext: context, viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] });
      renderTaskRef.current.promise.catch((reason) => { if (reason?.name !== "RenderingCancelledException") setError(reason?.message || "Không thể vẽ trang PDF"); });
    }).catch((reason) => { if (!cancelled) setError(reason?.message || "Không thể tải trang PDF"); });
    return () => { cancelled = true; renderTaskRef.current?.cancel(); };
  }, [pdf, page, scale, rotation]);

  useEffect(() => {
    if (!citationPage || !pdf) return;
    setCitationQuote(evidenceQuote || "");
    setCitationBbox(normalizedBbox(evidenceBbox));
    setPage(Math.min(Math.max(1, citationPage), pdf.numPages));
    viewportRef.current?.scrollTo({ top: 0, left: 0, behavior: "smooth" });
  }, [citationPage, evidenceQuote, evidenceBbox, pdf]);

  const compact = (value) => String(value ?? "").normalize("NFKC").replace(/\s+/g, "").toLocaleLowerCase("vi");
  const compactItems = textItems.map((item) => compact(item.str));
  const joinedItems = compactItems.join("");
  const quoteCompact = compact(citationQuote);
  const quoteStart = quoteCompact ? joinedItems.indexOf(quoteCompact) : -1;
  const itemRanges = [];
  let itemCursor = 0;
  compactItems.forEach((value) => { itemRanges.push([itemCursor, itemCursor + value.length]); itemCursor += value.length; });
  const derivedBoxes = textViewport ? textItems.flatMap((item, index) => {
    const transformed = multiplyTransform(textViewport.transform, item.transform || [1, 0, 0, 1, 0, 0]);
    const fontSize = Math.max(6, Math.hypot(transformed[2], transformed[3]));
    const [rangeStart, rangeEnd] = itemRanges[index] || [0, 0];
    const hit = quoteStart >= 0 && rangeEnd > quoteStart && rangeStart < quoteStart + quoteCompact.length;
    if (!hit) return [];
    const left = Math.max(0, Math.min(1, transformed[4] / textViewport.width));
    const top = Math.max(0, Math.min(1, (transformed[5] - fontSize) / textViewport.height));
    const right = Math.max(left, Math.min(1, (transformed[4] + Math.max(2, Number(item.width || 0) * textViewport.scale)) / textViewport.width));
    const bottom = Math.max(top, Math.min(1, (transformed[5] + Math.max(6, fontSize * .18)) / textViewport.height));
    return [[left, top, right, bottom]];
  }) : [];
  const derivedBox = derivedBoxes.length ? derivedBoxes.reduce((box, item) => [Math.min(box[0], item[0]), Math.min(box[1], item[1]), Math.max(box[2], item[2]), Math.max(box[3], item[3])]) : null;
  // evidence-hit is the legacy text-span marker; evidence-box is now normalized and scale invariant.
  const evidenceBoxes = rotation === 0 ? (citationBbox ? [citationBbox] : derivedBox ? [derivedBox] : []) : [];
  const textLayer = textViewport && <div className="pdf-text-layer" aria-hidden="true" style={{ width: textViewport.width, height: textViewport.height, left: "50%", top: 30, transform: "translateX(-50%)" }}><div className="evidence-box-layer">{evidenceBoxes.map((box, index) => <span className="evidence-box" key={`${box.join("-")}-${index}`} style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }} />)}</div></div>;

  const fitWidth = useCallback(async () => {
    if (!pdf || !viewportRef.current) return;
    const pdfPage = await pdf.getPage(page);
    const base = pdfPage.getViewport({ scale: 1, rotation });
    setScale(Math.max(.35, Math.min(2.5, (viewportRef.current.clientWidth - 56) / base.width)));
  }, [pdf, page, rotation]);

  if (!document) return <div className="empty-reader"><div className="empty-icon">PDF</div><h2>Chọn hoặc thêm tài liệu</h2><p>Tài liệu được lưu theo phiên làm việc và mở trực tiếp trong trình đọc PDF.</p></div>;

  return <section className="reader-shell">
    <header className="reader-toolbar">
      <div className="reader-file"><strong>{document.file_name}</strong><span>{formatBytes(document.byte_size)} · {processingLabel(document.extraction_status)}</span></div>
      {onReextract && !["queued", "processing"].includes(document.extraction_status) && <button className="reextract-button" type="button" title="Đọc lại tài liệu; kết quả cũ được lưu trữ" disabled={reextractDisabled} onClick={() => onReextract(document)}><Icon name="refresh" size={13} /> Trích xuất lại</button>}
      <div className="page-control"><button aria-label="Trang trước" title="Trang trước" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><Icon name="arrowLeft" /></button><span>{page} / {pdf?.numPages ?? document.page_count ?? "—"}</span><button aria-label="Trang sau" title="Trang sau" disabled={!pdf || page >= pdf.numPages} onClick={() => setPage((value) => value + 1)}><Icon name="arrowRight" /></button></div>
      <div className="zoom-control"><button aria-label="Thu nhỏ" title="Thu nhỏ" onClick={() => setScale((value) => Math.max(.35, value - .15))}><Icon name="minus" /></button><span>{Math.round(scale * 100)}%</span><button aria-label="Phóng to" title="Phóng to" onClick={() => setScale((value) => Math.min(2.5, value + .15))}><Icon name="plus" /></button><button aria-label="Vừa chiều rộng" title="Vừa chiều rộng" onClick={fitWidth}><Icon name="fit" /></button><button aria-label="Xoay tài liệu" title="Xoay tài liệu" onClick={() => setRotation((value) => (value + 90) % 360)}><Icon name="rotate" /></button></div>
    </header>
    <div className={`pdf-viewport ${dragRef.current ? "dragging" : ""}`} ref={viewportRef}
      onPointerDown={(event) => { const node = viewportRef.current; dragRef.current = { x: event.clientX, y: event.clientY, left: node.scrollLeft, top: node.scrollTop }; node.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => { if (!dragRef.current) return; const node = viewportRef.current; node.scrollLeft = dragRef.current.left - (event.clientX - dragRef.current.x); node.scrollTop = dragRef.current.top - (event.clientY - dragRef.current.y); }}
      onPointerUp={() => { dragRef.current = null; }}
      onPointerCancel={() => { dragRef.current = null; }}
      onWheel={(event) => { if (!event.ctrlKey) return; event.preventDefault(); setScale((value) => Math.max(.35, Math.min(2.5, value + (event.deltaY < 0 ? .1 : -.1)))); }}>
      {loading && <div className="reader-loading" role="status">Đang mở tài liệu…</div>}
      {error && <div className="reader-error" role="alert">Không thể render PDF: {error}</div>}
      <div className="canvas-mat"><canvas ref={canvasRef} />{textLayer}</div>
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
  useEffect(() => { setProfile(user); setDisplayName(user?.display_name ?? ""); }, [user]);
  const initial = (profile?.display_name || profile?.email || "S").trim().slice(0, 1).toUpperCase();
  const saveProfile = async (event) => {
    event.preventDefault();
    if (!displayName.trim()) return;
    setSaving(true); setError("");
    try {
      const body = await request("/api/v1/settings/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: displayName.trim() }) });
      setProfile(body.user); setEditing(false);
    } catch (reason) { setError(reason.message || "Không thể lưu hồ sơ."); }
    finally { setSaving(false); }
  };
  return <div className="profile-menu">
    <button className="profile-chip" type="button" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((value) => !value)}>
      <span className="profile-avatar">{initial}</span>
      <span className="profile-copy"><b>{profile?.display_name || "Workspace cá nhân"}</b><small>{profile?.email || "Chế độ demo"}</small></span>
      <Icon name="chevronDown" size={13} />
    </button>
    {open && <div className="profile-popover" role="menu">
      <div className="profile-summary"><span className="profile-avatar large">{initial}</span><div><b>{profile?.display_name || "Workspace cá nhân"}</b><small>{profile?.email || "Không yêu cầu đăng nhập"}</small></div></div>
      <div className="profile-meta"><Icon name="user" size={14} /><span>Tài khoản và dữ liệu được phân tách theo phiên làm việc.</span></div>
      {onNavigate && !editing && <><button className="profile-manage" type="button" onClick={() => { setOpen(false); onNavigate("/app/settings/profile"); }}><Icon name="user" size={14} /> Hồ sơ tài khoản</button><button className="profile-manage" type="button" onClick={() => { setOpen(false); onNavigate("/app/settings/preferences"); }}><Icon name="settings" size={14} /> Tuỳ chọn giao diện</button><button className="profile-manage" type="button" onClick={() => { setOpen(false); onNavigate("/app/settings/security"); }}><Icon name="trace" size={14} /> Bảo mật</button></>}
      {onSignOut && !editing && <button className="profile-manage" type="button" onClick={() => setEditing(true)}><Icon name="edit" size={14} /> Chỉnh sửa nhanh</button>}
      {onSignOut && editing && <form className="profile-edit-form" onSubmit={saveProfile}><label>Tên hiển thị<input autoFocus value={displayName} maxLength={120} onChange={(event) => setDisplayName(event.target.value)} /></label>{error && <p role="alert">{error}</p>}<div><button type="button" onClick={() => { setDisplayName(profile?.display_name ?? ""); setEditing(false); setError(""); }}>Hủy</button><button type="submit" disabled={saving || !displayName.trim()}>{saving ? "Đang lưu…" : "Lưu hồ sơ"}</button></div></form>}
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
    const closeOnKey = (event) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", closeOnPointer);
    document.addEventListener("keydown", closeOnKey);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointer);
      document.removeEventListener("keydown", closeOnKey);
    };
  }, [open]);
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
      <button type="button" role="menuitem" onClick={() => { setOpen(false); onRename(); }}><Icon name="edit" size={13} /> Đổi tên</button>
      <button type="button" role="menuitem" className="danger" onClick={() => { setOpen(false); onDelete(); }}><Icon name="trash" size={13} /> Xóa</button>
    </div>, document.body)}
  </>;
}

function ResourceDialog({ dialog, busy, onClose, onConfirm }) {
  const [value, setValue] = useState(dialog?.value ?? "");
  useEffect(() => setValue(dialog?.value ?? ""), [dialog?.kind, dialog?.value]);
  if (!dialog) return null;
  const isDelete = dialog.kind.startsWith("delete");
  return <div className="resource-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="resource-modal" role="dialog" aria-modal="true" aria-labelledby="resource-dialog-title">
      <div className={`resource-modal-icon ${isDelete ? "danger" : ""}`}><Icon name={isDelete ? "trash" : "edit"} size={19} /></div>
      <div><p className="dialog-kicker">{isDelete ? "XÁC NHẬN THAO TÁC" : "CHỈNH SỬA"}</p><h2 id="resource-dialog-title">{dialog.title}</h2><p>{dialog.description}</p></div>
      {isDelete ? <div className="dialog-warning">Thao tác này sẽ ẩn mục khỏi workspace. Dữ liệu nguồn được archive để bảo toàn lịch sử.</div> : <label className="dialog-input-label">Tên hiển thị<input autoFocus value={value} onChange={(event) => setValue(event.target.value)} maxLength={dialog.maxLength ?? 255} /></label>}
      <div className="resource-modal-actions"><button type="button" className="dialog-secondary" onClick={onClose} disabled={busy}>Hủy</button><button type="button" className={isDelete ? "dialog-danger" : "dialog-primary"} disabled={busy || (!isDelete && !value.trim())} onClick={() => onConfirm(dialog, value.trim())}>{busy ? "Đang lưu…" : isDelete ? "Xóa khỏi workspace" : "Lưu thay đổi"}</button></div>
    </section>
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
  const [runtimeHealth, setRuntimeHealth] = useState(null);
  const [bootError, setBootError] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState("info");
  const [retryQuestion, setRetryQuestion] = useState("");
  const [search, setSearch] = useState("");
  const [citationPage, setCitationPage] = useState(null);
  const [citationQuote, setCitationQuote] = useState("");
  const [citationBbox, setCitationBbox] = useState(null);
  const [evidenceData, setEvidenceData] = useState(null);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [pendingMessages, setPendingMessages] = useState([]);
  const [activeJobs, setActiveJobs] = useState([]);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [requestMetrics, setRequestMetrics] = useState([]);
  const [performanceOpen, setPerformanceOpen] = useState(false);
  const [resourceDialog, setResourceDialog] = useState(null);
  const uploadRef = useRef(null);
  const bootedRef = useRef(false);
  const refreshSequenceRef = useRef(0);
  const sessionRefreshSequenceRef = useRef(0);
  const uploadQueryConsumedRef = useRef(false);

  const showNotice = useCallback((message, kind = "info") => { setNotice(userFacingError(message)); setNoticeKind(kind); }, []);
  const clearNotice = useCallback(() => { setNotice(""); setRetryQuestion(""); }, []);
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

  const refresh = useCallback(async (preferredSession) => {
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
  useEffect(() => { setEvidenceData(null); setCitationPage(null); setCitationQuote(""); setCitationBbox(null); }, [activeSession?.id, activeDocument?.id]);
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
  const combinedMessages = [...persistedMessages, ...pendingForActive.filter((message) => !persistedIds.has(message.id))];
  // A legacy snapshot may have replies separated from their questions. Use
  // the persisted reply link, while retaining the order of question turns.
  const repliesByQuestion = new Map();
  for (const message of combinedMessages) {
    if (message.role === "assistant" && message.reply_to_message_id) {
      const replies = repliesByQuestion.get(message.reply_to_message_id) ?? [];
      replies.push(message);
      repliesByQuestion.set(message.reply_to_message_id, replies);
    }
  }
  const questionIds = new Set(combinedMessages.filter((message) => message.role === "user").map((message) => message.id));
  const messages = combinedMessages.flatMap((message) => {
    if (message.role === "assistant" && questionIds.has(message.reply_to_message_id)) return [];
    return message.role === "user" ? [message, ...(repliesByQuestion.get(message.id) ?? [])] : [message];
  });
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
  const forceChatScrollRef = useRef(false);
  const retryMetaRef = useRef(null);

  useEffect(() => {
    const node = document.querySelector(".chat-body");
    if (!node) return undefined;
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
    if (!forceChatScrollRef.current && !nearBottom) return undefined;
    const force = forceChatScrollRef.current;
    const frame = window.requestAnimationFrame(() => node.scrollTo({ top: node.scrollHeight, behavior: force ? "smooth" : "auto" }));
    forceChatScrollRef.current = false;
    return () => window.cancelAnimationFrame(frame);
  }, [messages.length, messages.at(-1)?.id, messages.at(-1)?.body, messages.at(-1)?.status, activeSession?.id, activeDocument?.id]);

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
      }
      setResourceDialog(null);
    } catch (error) {
      showNotice(error.message, "error");
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

  async function submitQuestion(questionInput) {
    const question = questionInput?.trim();
    const idempotencyKey = retryMetaRef.current?.question === question ? retryMetaRef.current.key : crypto.randomUUID();
    if (!question || requestInFlightRef.current || busy || !activeDocument || !activeSession) return;
    if (activeDocument.extraction_status === "failed") {
      showNotice(`Tài liệu chưa thể đọc nên chưa thể trả lời. ${canReextract ? "Bấm Trích xuất lại ở thanh trên PDF." : "Hãy thử xử lý lại tài liệu trong Trung tâm tác vụ."}`, "error");
      return;
    }
    requestInFlightRef.current = true;
    forceChatScrollRef.current = true;
    const userId = crypto.randomUUID();
    const pendingId = crypto.randomUUID();
    const scope = { session_id: activeSession.id, document_id: activeDocument.id };
    setPendingMessages((current) => [...current.filter((message) => !message.failed), { id: userId, role: "user", body: question, ...scope, pending: true }, { id: pendingId, role: "assistant", body: "", structured_answer: { pending: true }, ...scope, pending: true }]);
    setQuery(""); setRetryQuestion(""); setBusy(true); clearNotice();
    try {
      const result = await request(`/api/v1/sessions/${activeSession.id}/messages`, { method: "POST", body: JSON.stringify({ document_id: activeDocument.id, question }), headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey } });
      if (result.job) setActiveJobs((current) => [result.job, ...current.filter((job) => job.id !== result.job.id)]);
      // The API has accepted the turn; show its durable message IDs now and
      // release the composer while the background answer job is still running.
      setPendingMessages((current) => current.map((message) => message.id === userId
        ? { ...result.user_message, ...scope, pending: false }
        : message.id === pendingId ? { ...result.assistant_message, ...scope, pending: false } : message));
      requestInFlightRef.current = false;
      setBusy(false);
      retryMetaRef.current = null;
      const firstCitation = result.assistant_message?.citations?.[0];
      if (firstCitation?.page) { setCitationPage(firstCitation.page); setCitationQuote(firstCitation.quote ?? ""); setCitationBbox(normalizedBbox(firstCitation.bbox)); }
      try { await refreshSessionDetail(activeSession.id); }
      catch (refreshError) {
        showNotice(`Đã nhận câu trả lời nhưng chưa tải lại lịch sử: ${refreshError.message}`, "error");
      }
    } catch (error) {
      // Keep a failed turn in the transcript. Removing it made a rejected or
      // unreachable request look like the whole conversation had reset.
      setPendingMessages((current) => current.map((message) => message.id === userId
        ? { ...message, pending: false, failed: true, status: "failed" }
        : message.id === pendingId ? { ...message, body: error.message, pending: false, failed: true, status: "failed", structured_answer: null } : message));
      retryMetaRef.current = { question, key: idempotencyKey };
      setRetryQuestion(question); showNotice(error.message, "error");
    } finally { requestInFlightRef.current = false; setBusy(false); }
  }

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

  async function openEvidence() {
    if (!activeSession || !activeDocument || activeDocument.extraction_status !== "ready") return;
    setEvidenceBusy(true);
    try { setEvidenceData(await request(`/api/v1/sessions/${activeSession.id}/documents/${activeDocument.id}/evidences`)); }
    catch (error) { showNotice(error.message, "error"); }
    finally { setEvidenceBusy(false); }
  }

  // PostgreSQL keeps completed extractions immutable; there a failed document
  // is retried from the job center instead.
  const canReextract = runtimeHealth?.persistence_backend === "json";

  async function reextractDocument(document) {
    if (!activeSession || !document) return;
    if (document.extraction_status === "ready" && !window.confirm("Trích xuất lại tài liệu này? Kết quả cũ được lưu trữ, số đã sửa được giữ, các câu trả lời cũ sẽ được đánh dấu cần tính lại.")) return;
    setBusy(true);
    try {
      const result = await request(`/api/v1/sessions/${activeSession.id}/documents/${document.id}/extraction`, { method: "POST" });
      await refreshSessionDetail(activeSession.id);
      setEvidenceData(null);
      const affected = result.affected_message_ids?.length ?? 0;
      showNotice(`Đang trích xuất lại ${document.file_name}.${affected ? ` ${affected} câu trả lời cũ cần tính lại.` : ""}`);
    } catch (error) { showNotice(error.message, "error"); }
    finally { setBusy(false); }
  }

  async function saveEvidence(evidence, numeric_value, reason) {
    if (!activeSession || !activeDocument) return;
    setEvidenceBusy(true);
    try {
      const result = await request(`/api/v1/sessions/${activeSession.id}/documents/${activeDocument.id}/evidences/${encodeURIComponent(evidence.evidence_key)}/revisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ numeric_value, reason, expected_revision_id: evidence.current_revision_id }) });
      setEvidenceData(await request(`/api/v1/sessions/${activeSession.id}/documents/${activeDocument.id}/evidences`));
      await refresh(activeSession.id);
      showNotice(`Đã lưu ${result.revision.old_numeric_value} → ${result.revision.numeric_value}. ${result.affected_message_ids?.length ? "Câu trả lời liên quan cần tính lại." : ""}`);
    } catch (error) { showNotice(error.message, "error"); }
    finally { setEvidenceBusy(false); }
  }

  const nextTheme = preference === "light" ? "dark" : preference === "dark" ? "system" : "light";
  const activeJobCount = activeJobs.filter((job) => ["queued", "running"].includes(job.status)).length;
  const readinessState = runtimeHealth?.readiness?.status ?? (runtimeHealth ? "checking" : "offline");
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
    <header className="topbar">
      <div className="brand"><span>S</span><div><strong>SourceLens</strong><small>Document intelligence</small></div></div>
      <div className="topbar-context"><span>WORKSPACE</span><strong>{activeDocument?.file_name ?? "Thư viện tài liệu"}</strong></div>
      <nav className="top-nav" aria-label="Điều hướng chính"><button className="top-nav-item active" type="button"><Icon name="grid" size={14} /> Workspace</button><button className="top-nav-item" type="button" onClick={() => onNavigate?.("/app/library")}><Icon name="folder" size={14} /> Tài liệu</button></nav>
      <div className="top-actions">
        <span className={`connection-pill ${readinessState === "ready" ? "online" : readinessState === "offline" ? "offline" : "checking"}`} title={readinessBlockers || readinessLabel}><i></i>{readinessLabel}</span>
        {activeJobs.length > 0 && <button className="job-pill" type="button" aria-label={`Mở trung tâm tác vụ, ${activeJobs.length} tác vụ`} onClick={() => setJobsOpen(true)}><i></i>{activeJobCount > 0 ? `${activeJobCount} đang xử lý` : "Trung tâm tác vụ"}</button>}
        <button className="icon-button" type="button" title={`Chuyển giao diện sang ${nextTheme}`} aria-label={`Chuyển giao diện sang ${nextTheme}`} onClick={() => setPreference(nextTheme)}><Icon name={resolvedTheme === "dark" ? "moon" : "sun"} size={15} /></button>
        <button className="audit-button" disabled={!activeDocument || activeDocument.extraction_status !== "ready" || evidenceBusy} onClick={openEvidence}><Icon name="link" size={14} /> Bằng chứng</button>
        <ProfileMenu user={user} onSignOut={onSignOut} onNavigate={onNavigate} />
        <input ref={uploadRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => upload(event.target.files?.[0])} />
      </div>
    </header>
    <main className="workspace" id="main-content">
      <SessionBrowser sessions={sessions} filteredSessions={filteredSessions} activeSession={activeSession} activeDocument={activeDocument} booting={booting} search={search} onSearch={setSearch} busy={busy} onSelectSession={(session) => { setActiveSessionId(session.id); setActiveDocumentId(session.documents[0]?.id ?? null); }} onSelectDocument={setActiveDocumentId} onCreate={createSession} onUpload={() => uploadRef.current?.click()} onDialog={setResourceDialog} onNavigate={onNavigate} />
      <section className="reader-column"><PdfViewer document={activeDocument} sessionId={activeSession?.id} citationPage={citationPage} evidenceQuote={citationQuote} evidenceBbox={citationBbox} onReextract={canReextract ? reextractDocument : undefined} reextractDisabled={busy} />{notice && <div className={`toast ${noticeKind}`} role={noticeKind === "error" ? "alert" : "status"} aria-live="polite"><span>{notice}</span>{retryQuestion && <button onClick={() => submitQuestion(retryQuestion)} disabled={busy}><Icon name="refresh" size={13} /> Thử lại</button>}<button className="toast-close" aria-label="Đóng thông báo" onClick={clearNotice}><Icon name="close" size={13} /></button></div>}</section>
      <aside className="chat-column">
        <header className="chat-header"><div className="ai-avatar">S</div><div><h2>Trợ lý tài liệu</h2><span>{activeDocument ? activeDocument.file_name : "Chưa chọn tài liệu"}</span></div><span className="mode-badge">{modeLabel}</span></header>
        <div className="chat-body">
          {!messages.length && <div className="welcome"><div className="welcome-mark"><Icon name="spark" size={18} /></div><h3>Bắt đầu với tài liệu của bạn</h3><p>Đặt câu hỏi để nhận câu trả lời có dẫn nguồn, trích dẫn theo trang và cấu trúc rõ ràng.</p>{activeDocument?.extraction_status === "ready" && <button onClick={() => setQuery("Tóm tắt nội dung chính của tài liệu")}>Tóm tắt tài liệu</button>}</div>}
          {messages.map((message, index) => <article key={message.id} className={`message ${message.role} ${message.failed || message.status === "failed" ? "failed" : ""}`}><span className="message-avatar">{message.role === "user" ? "B" : "S"}</span><div><small>{message.role === "user" ? "Bạn" : "Trợ lý SourceLens"}</small><StructuredAnswer answer={presentationAnswer(message)} fallback={message.body} onCitation={(page, quote, bbox) => { setCitationPage(page); setCitationQuote(quote); setCitationBbox(normalizedBbox(bbox)); }} />{message.role === "assistant" && message.status === "processing" && <button className="retry-answer-button" type="button" onClick={() => stopAnswer(message)}>Dừng trả lời</button>}{(message.failed || message.status === "failed") && message.role === "assistant" && <button className="retry-answer-button" type="button" onClick={() => { const previous = messages.find((item) => item.id === message.reply_to_message_id) ?? messages[index - 1]; if (previous?.role === "user") submitQuestion(previous.body); }} disabled={busy}><Icon name="refresh" size={13} /> Thử lại</button>}{message.role === "user" && !message.pending && <button className="message-icon-button" type="button" aria-label="Sửa câu hỏi" title="Sửa câu hỏi" onClick={() => { setQuery(message.body); document.querySelector('.chat-composer textarea')?.focus(); }}><Icon name="edit" size={14} /></button>}{message.role === "assistant" && message.body && !message.pending && !message.failed && message.status !== "failed" && message.status !== "processing" && <button className="message-icon-button" type="button" aria-label="Sao chép câu trả lời" title="Sao chép câu trả lời" onClick={async () => { try { await navigator.clipboard.writeText(message.body); showNotice("Đã sao chép."); } catch { showNotice("Không thể sao chép.", "error"); } }}><Icon name="copy" size={14} /></button>}{message.needs_update && <div className="answer-status-note stale-answer"><Icon name="refresh" size={13} /><span>Dữ liệu nguồn đã thay đổi; câu trả lời này cần được cập nhật.</span></div>}{!message.structured_answer?.evidence?.length && message.citations?.map((citation, citationIndex) => <button className="citation" key={citationIndex} onClick={() => { setCitationPage(citation.page); setCitationQuote(""); setCitationBbox(normalizedBbox(citation.bbox)); }}><Icon name="link" size={12} /> Trang {citation.page}{citation.bbox ? " · vùng trích dẫn" : ""}</button>)}</div></article>)}
        </div>
        <form className="chat-composer" onSubmit={ask}><textarea aria-label="Câu hỏi về tài liệu" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={!activeDocument ? "Thêm tài liệu để bắt đầu" : activeDocument.extraction_status === "ready" ? "Đặt câu hỏi về tài liệu…" : activeDocument.extraction_status === "failed" ? canReextract ? "Chưa thể đọc tài liệu, bấm Trích xuất lại" : "Chưa thể đọc tài liệu — mở Trung tâm tác vụ để thử lại" : "Đặt câu hỏi — trợ lý sẽ trả lời khi tài liệu sẵn sàng…"} disabled={!activeDocument || busy} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} /><div><span>{activeDocument?.extraction_status === "ready" ? "Trợ lý sẵn sàng" : activeDocument?.extraction_status === "failed" ? "Tài liệu chưa đọc được" : activeDocument?.extraction_status === "queued" || activeDocument?.extraction_status === "processing" ? "Câu hỏi sẽ được xử lý sau khi đọc tài liệu" : "Chưa sẵn sàng"}</span><button aria-label="Gửi câu hỏi" title="Gửi câu hỏi" disabled={!activeDocument || activeDocument.extraction_status === "failed" || busy || !query.trim()}><Icon name="send" size={15} /></button></div></form>
      </aside>
      <EvidenceDrawer data={evidenceData} busy={evidenceBusy} onClose={() => setEvidenceData(null)} onFocus={(evidence) => { setCitationPage(evidence.page_number); setCitationQuote(""); setCitationBbox(normalizedBbox(evidence.bbox)); }} onSave={saveEvidence} />
      <ResourceDialog dialog={resourceDialog} busy={busy} onClose={() => setResourceDialog(null)} onConfirm={confirmResourceAction} />
      <JobCenterDrawer jobs={jobsOpen ? activeJobs : null} busy={busy} onClose={() => setJobsOpen(false)} onAction={handleJobAction} />
    </main>
  </div>;
}

export default App;
