import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const API = window.SOURCELENS_API ?? "http://127.0.0.1:8000";
const SESSION_KEY = "sourcelens-active-session";
const DOCUMENT_KEY = "sourcelens-active-document";
const REQUEST_TIMEOUT_MS = 35_000;

function Icon({ name, size = 16 }) {
  const paths = {
    add: <path d="M12 5v14M5 12h14" />,
    arrowLeft: <><path d="m15 18-6-6 6-6" /><path d="M9 12h10" /></>,
    arrowRight: <><path d="m9 18 6-6-6-6" /><path d="M5 12h10" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    fit: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
    folder: <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h4l2 2h7A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z" />,
    link: <><path d="M10 13a5 5 0 0 0 7.1.1l1.4-1.4a5 5 0 0 0-7.1-7.1L10 6" /><path d="M14 11a5 5 0 0 0-7.1-.1l-1.4 1.4a5 5 0 0 0 7.1 7.1L14 18" /></>,
    minus: <path d="M5 12h14" />,
    plus: <path d="M12 5v14M5 12h14" />,
    refresh: <><path d="M20 11a8 8 0 0 0-14.7-3L4 10" /><path d="M4 5v5h5" /><path d="M4 13a8 8 0 0 0 14.7 3L20 14" /><path d="M20 19v-5h-5" /></>,
    rotate: <><path d="M4 9a8 8 0 0 1 13.7-3L20 8" /><path d="M20 3v5h-5" /><path d="M20 15a8 8 0 0 1-13.7 3L4 16" /><path d="M4 21v-5h5" /></>,
    send: <><path d="m4 4 16 8-16 8 3-8z" /><path d="M7 12h13" /></>,
    spark: <><path d="m12 3 1.3 5.7L19 10l-5.7 1.3L12 17l-1.3-5.7L5 10l5.7-1.3z" /><path d="m19 16 .6 2.4L22 19l-2.4.6z" /></>,
    trace: <><path d="M5 5h4v4H5zM15 15h4v4h-4z" /><path d="M9 7h3a3 3 0 0 1 3 3v5" /><path d="M12 15h3" /></>,
    upload: <><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M5 20h14" /></>,
  };
  return <svg className="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${API}${path}`, {
      ...options,
      signal: options.signal ?? controller.signal,
      headers: { "X-Trace-Id": crypto.randomUUID(), ...(options.headers ?? {}) },
    });
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("Yêu cầu quá thời gian chờ. Hãy thử lại.");
    throw new Error("Không kết nối được tới backend. Kiểm tra API đang chạy rồi thử lại.");
  } finally {
    window.clearTimeout(timeout);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    if (detail && typeof detail === "object") throw new Error(`${detail.code ? `${detail.code}: ` : ""}${detail.message ?? `HTTP ${response.status}`}`);
    throw new Error(detail ?? `HTTP ${response.status}`);
  }
  return body;
}

function formatBytes(value = 0) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function normalizedBbox(value) {
  const raw = Array.isArray(value) ? value : [value?.x0, value?.y0, value?.x1, value?.y1];
  if (raw.length !== 4 || raw.some((item) => !Number.isFinite(Number(item)))) return null;
  const [x0, y0, x1, y1] = raw.map((item) => Math.max(0, Math.min(1, Number(item))));
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

function traceValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "—");
}

function presentationAnswer(message) {
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
    warnings: ["Đang dùng retrieval cục bộ; bật OpenRouter/Gemini để nhận phân tích có cấu trúc và bảng."],
    cited_pages: page ? [page] : [],
  };
}

function AuditEvent({ event, index }) {
  const excluded = new Set(["stage", "status", "at", "context_manifest"]);
  const fields = Object.entries(event).filter(([key]) => !excluded.has(key));
  return <details className={`audit-event ${event.status}`} open={index === 0}>
    <summary><span className={`trace-dot ${event.status}`}></span><span className="audit-event-main"><b>{event.stage}</b><small>{event.status} · {event.at}</small></span><span className="audit-chevron">⌄</span></summary>
    <div className="audit-event-body">{fields.map(([key, value]) => <div className="audit-field" key={key}><span>{key}</span><code>{traceValue(value)}</code></div>)}{event.context_manifest?.map((item) => <div className="audit-context" key={`${event.stage}-${item.page}-${item.text_sha256}`}><strong>Context p{item.page}</strong><span>{item.chars} ký tự</span><code>sha256:{item.text_sha256.slice(0, 16)}…</code></div>)}</div>
  </details>;
}

function AuditDrawer({ traceData, traceMessage, activeDocument, onClose }) {
  if (!traceData) return null;
  const trace = traceData.trace ?? [];
  const retrieval = trace.find((event) => event.stage === "retrieval");
  const provider = trace.find((event) => event.stage === "ai_provider");
  const calculation = trace.find((event) => event.stage === "calculation");
  const persistence = trace.find((event) => event.stage === "persistence");
  const requestPayload = { session_id: traceData.session_id, document_id: traceMessage?.document_id ?? activeDocument?.id, question: traceMessage?.question ?? null };
  const responseSnapshot = { message_id: traceData.message_id, mode: traceMessage?.mode ?? null, question_plan: traceMessage?.question_plan ?? null, calculation_result: traceMessage?.calculation_result ?? null, answer_inputs: traceMessage?.answer_inputs ?? [], citations: traceMessage?.citations ?? [], structured_answer: Boolean(traceMessage?.structured_answer), body_chars: traceMessage?.body?.length ?? 0 };
  return <section className="audit-drawer" role="dialog" aria-label="Data flow audit">
    <header className="audit-drawer-header"><div><span className="audit-kicker">INSPECTOR</span><h3>Data flow audit</h3><small>{trace.length} events · trace_id {traceData.trace_id ?? "—"}</small></div><button aria-label="Đóng audit inspector" onClick={onClose}><Icon name="close" size={15} /></button></header>
    <div className="audit-scope-grid"><div><span>SESSION</span><code>{traceData.session_id ?? "—"}</code></div><div><span>DOCUMENT</span><code>{activeDocument?.id ?? traceMessage?.document_id ?? "—"}</code></div><div><span>MESSAGE</span><code>{traceData.message_id ?? "—"}</code></div></div>
    <div className="audit-request"><span>REQUEST</span><p>{traceMessage?.question ?? "Payload câu hỏi không nằm trong trace cũ."}</p></div>
    <div className="audit-payload-grid"><div><span>REQUEST PAYLOAD</span><pre>{JSON.stringify(requestPayload, null, 2)}</pre></div><div><span>RESPONSE SNAPSHOT</span><pre>{JSON.stringify(responseSnapshot, null, 2)}</pre></div></div>
    <div className="audit-summary"><div><span>RETRIEVAL</span><b>{retrieval?.status ?? "—"}</b><small>{retrieval?.pages ? `trang ${retrieval.pages.join(", ")}` : "không chạy"}</small></div><div><span>AI / CALCULATOR</span><b>{calculation?.status ?? provider?.status ?? "deterministic"}</b><small>{calculation?.formula_id ?? provider?.provider ?? "question planner"}</small></div><div><span>PERSISTENCE</span><b>{persistence?.status ?? "—"}</b><small>{persistence?.artifact ?? "chưa ghi"}</small></div></div>
    <div className="audit-timeline">{trace.map((event, index) => <AuditEvent event={event} index={index} key={`${event.stage}-${event.at}-${index}`} />)}</div>
  </section>;
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
      <button className="evidence-record-main" onClick={() => onFocus(evidence)}><span>p.{evidence.page_number} · {evidence.method_label}</span><b>{evidence.current_numeric_value}</b><small>Gốc: {evidence.original_numeric_value} · {evidence.revision_count} revision</small><code>{evidence.evidence_key}</code></button>
      {editingKey === evidence.evidence_key ? <form className="evidence-edit-form" onSubmit={(event) => { event.preventDefault(); onSave(evidence, value, reason).then(() => setEditingKey(null)); }}><label>Giá trị mới<input autoFocus value={value} onChange={(event) => setValue(event.target.value)} required /></label><label>Lý do sửa<textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength="3" required placeholder="Ví dụ: Đối chiếu lại PDF gốc" /></label><div><button type="button" onClick={() => setEditingKey(null)}>Hủy</button><button type="submit" disabled={busy}>Lưu revision</button></div></form> : <button className="evidence-edit-button" onClick={() => beginEdit(evidence)} disabled={busy}>Sửa số</button>}
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
    {answer.summary && <p className="answer-summary">{answer.summary}</p>}
    {answer.claims?.length > 0 && <section className="answer-section answer-claims"><h4>Claims và căn cứ</h4>{answer.claims.map((claim, index) => <div className="claim-card" key={`${claim.claim}-${index}`}>
      <p>{claim.claim}</p>
      {claim.evidence_quotes?.map((quote, quoteIndex) => <button className="evidence-quote" key={`${quote}-${quoteIndex}`} onClick={() => onCitation?.(claim.evidence_pages?.[quoteIndex] ?? claim.evidence_pages?.[0], quote)}><span className="evidence-quote-label"><Icon name="link" size={12} /> Evidence</span><span>“{quote}”</span></button>)}
      {claim.evidence_pages?.length > 0 && <div className="evidence-pages">{claim.evidence_pages.map((page) => <button className="citation" key={page} onClick={() => onCitation?.(page, claim.evidence_quotes?.[0] ?? "")}><Icon name="link" size={12} /> Trang {page}</button>)}</div>}
    </div>)}</section>}
    {answer.sections?.map((section, index) => <section className="answer-section" key={`${section.heading}-${index}`}><h4>{section.heading}</h4>{section.points?.filter(Boolean).length > 0 && <ul>{section.points.filter(Boolean).map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}</ul>}</section>)}
    {answer.formulas?.length > 0 && <section className="answer-section"><h4>Công thức và tính toán</h4>{answer.formulas.map((formula, index) => <div className="formula-card" key={`${formula.name}-${index}`}><strong>{formula.name}</strong><code>{formula.expression}</code><span>Thay số: {formula.substitution || "Chưa đủ toán hạng"}</span><b>Kết quả: {formula.result ?? "Không xác định"}{formula.unit ? ` ${formula.unit}` : ""}</b>{["verified", "succeeded"].includes(formula.calculation?.status) ? <em className="formula-verified">✓ Calculator: {formula.calculation.computed_result} {formula.calculation.unit}</em> : <em className="formula-unverified">Calculator: {formula.calculation?.status ?? "chưa chạy"}</em>}</div>)}</section>}
    {answer.tables?.map((table, index) => <section className="answer-section" key={`${table.title}-${index}`}><h4>{table.title}</h4><div className="answer-table-wrap"><table className="answer-table"><thead><tr>{table.columns?.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{table.rows?.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div></section>)}
    {warnings.length > 0 && <div className="answer-warnings"><strong>Lưu ý</strong><ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
  </div>;
}

function PdfViewer({ document, sessionId, citationPage, evidenceQuote, evidenceBbox }) {
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
    try { task = pdfjs.getDocument({ url: fileUrl }); } catch (reason) {
      setLoading(false); setError(reason?.message || "Không thể khởi tạo PDF.js"); return undefined;
    }
    task.promise.then((loaded) => { if (!disposed) { setPdf(loaded); setLoading(false); } }).catch((reason) => { if (!disposed) { setError(reason?.message || "Không thể đọc PDF"); setLoading(false); } });
    return () => { disposed = true; task.destroy(); };
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
    const transformed = pdfjs.Util.transform(textViewport.transform, item.transform || [1, 0, 0, 1, 0, 0]);
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

  if (!document) return <div className="empty-reader"><div className="empty-icon">PDF</div><h2>Chọn hoặc tải một tài liệu</h2><p>SourceLens sẽ lưu file theo phiên và mở chính file đó bằng PDF.js.</p></div>;

  return <section className="reader-shell">
    <header className="reader-toolbar">
      <div className="reader-file"><strong>{document.file_name}</strong><span>{formatBytes(document.byte_size)} · {document.extraction_status === "ready" ? "Text index sẵn sàng" : document.extraction_status === "queued" ? "Đang trích text…" : "Trích text thất bại"}</span></div>
      <div className="page-control"><button aria-label="Trang trước" title="Trang trước" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><Icon name="arrowLeft" /></button><span>{page} / {pdf?.numPages ?? document.page_count ?? "—"}</span><button aria-label="Trang sau" title="Trang sau" disabled={!pdf || page >= pdf.numPages} onClick={() => setPage((value) => value + 1)}><Icon name="arrowRight" /></button></div>
      <div className="zoom-control"><button aria-label="Thu nhỏ" title="Thu nhỏ" onClick={() => setScale((value) => Math.max(.35, value - .15))}><Icon name="minus" /></button><span>{Math.round(scale * 100)}%</span><button aria-label="Phóng to" title="Phóng to" onClick={() => setScale((value) => Math.min(2.5, value + .15))}><Icon name="plus" /></button><button aria-label="Vừa chiều rộng" title="Vừa chiều rộng" onClick={fitWidth}><Icon name="fit" /></button><button aria-label="Xoay tài liệu" title="Xoay tài liệu" onClick={() => setRotation((value) => (value + 90) % 360)}><Icon name="rotate" /></button></div>
    </header>
    <div className={`pdf-viewport ${dragRef.current ? "dragging" : ""}`} ref={viewportRef}
      onPointerDown={(event) => { const node = viewportRef.current; dragRef.current = { x: event.clientX, y: event.clientY, left: node.scrollLeft, top: node.scrollTop }; node.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => { if (!dragRef.current) return; const node = viewportRef.current; node.scrollLeft = dragRef.current.left - (event.clientX - dragRef.current.x); node.scrollTop = dragRef.current.top - (event.clientY - dragRef.current.y); }}
      onPointerUp={() => { dragRef.current = null; }}
      onPointerCancel={() => { dragRef.current = null; }}
      onWheel={(event) => { if (!event.ctrlKey) return; event.preventDefault(); setScale((value) => Math.max(.35, Math.min(2.5, value + (event.deltaY < 0 ? .1 : -.1)))); }}>
      {loading && <div className="reader-loading" role="status">Đang mở PDF…</div>}
      {error && <div className="reader-error" role="alert">Không thể render PDF: {error}</div>}
      <div className="canvas-mat"><canvas ref={canvasRef} />{textLayer}</div>
    </div>
  </section>;
}

function App() {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(localStorage.getItem(SESSION_KEY));
  const [activeDocumentId, setActiveDocumentId] = useState(localStorage.getItem(DOCUMENT_KEY));
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(true);
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState("info");
  const [retryQuestion, setRetryQuestion] = useState("");
  const [search, setSearch] = useState("");
  const [citationPage, setCitationPage] = useState(null);
  const [citationQuote, setCitationQuote] = useState("");
  const [citationBbox, setCitationBbox] = useState(null);
  const [traceData, setTraceData] = useState(null);
  const [traceMessage, setTraceMessage] = useState(null);
  const [traceBusy, setTraceBusy] = useState(false);
  const [evidenceData, setEvidenceData] = useState(null);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [pendingMessages, setPendingMessages] = useState([]);
  const uploadRef = useRef(null);
  const bootedRef = useRef(false);

  const showNotice = useCallback((message, kind = "info") => { setNotice(message); setNoticeKind(kind); }, []);
  const clearNotice = useCallback(() => { setNotice(""); setRetryQuestion(""); }, []);

  const refresh = useCallback(async (preferredSession) => {
    const response = await request("/api/v1/sessions");
    let next = response.sessions ?? [];
    if (!next.length) {
      const created = await request("/api/v1/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "Phiên phân tích đầu tiên" }) });
      next = [created.session];
    }
    setSessions(next);
    const selected = preferredSession ?? activeSessionId;
    if (!next.some((item) => item.id === selected)) setActiveSessionId(next[0].id);
  }, [activeSessionId]);

  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;
    refresh().catch((error) => showNotice(error.message, "error")).finally(() => setBooting(false));
  }, [refresh, showNotice]);
  useEffect(() => { if (activeSessionId) localStorage.setItem(SESSION_KEY, activeSessionId); }, [activeSessionId]);
  useEffect(() => { if (activeDocumentId) localStorage.setItem(DOCUMENT_KEY, activeDocumentId); }, [activeDocumentId]);

  const activeSession = sessions.find((item) => item.id === activeSessionId) ?? sessions[0];
  const activeDocument = activeSession?.documents.find((item) => item.id === activeDocumentId) ?? activeSession?.documents[0] ?? null;
  useEffect(() => { if (activeDocument && activeDocument.id !== activeDocumentId) setActiveDocumentId(activeDocument.id); }, [activeSession?.id, activeDocument?.id, activeDocumentId]);
  useEffect(() => { setTraceData(null); setTraceMessage(null); setEvidenceData(null); setCitationPage(null); setCitationQuote(""); setCitationBbox(null); }, [activeSession?.id, activeDocument?.id]);
  useEffect(() => {
    if (!activeSession || activeDocument?.extraction_status !== "queued") return undefined;
    const timer = window.setInterval(() => refresh(activeSession.id).catch((error) => showNotice(error.message, "error")), 1500);
    return () => window.clearInterval(timer);
  }, [activeSession?.id, activeDocument?.id, activeDocument?.extraction_status, refresh, showNotice]);

  const filteredSessions = useMemo(() => sessions.filter((session) => session.title.toLowerCase().includes(search.toLowerCase()) || session.documents.some((document) => document.file_name.toLowerCase().includes(search.toLowerCase()))), [sessions, search]);
  const persistedMessages = (activeSession?.messages ?? []).filter((message) => !activeDocument || message.document_id === activeDocument.id);
  const messages = [...persistedMessages, ...pendingMessages.filter((message) => message.session_id === activeSession?.id && message.document_id === activeDocument?.id)];
  const modeLabel = messages.some((message) => message.mode?.startsWith("ai:")) ? "AI + grounded" : "retrieval local";
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant" && !message.pending && !message.failed);
  const requestInFlightRef = useRef(false);
  const forceChatScrollRef = useRef(false);

  useEffect(() => {
    const node = document.querySelector(".chat-body");
    if (!node) return undefined;
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
    if (!forceChatScrollRef.current && !nearBottom) return undefined;
    const force = forceChatScrollRef.current;
    const frame = window.requestAnimationFrame(() => node.scrollTo({ top: node.scrollHeight, behavior: force ? "smooth" : "auto" }));
    forceChatScrollRef.current = false;
    return () => window.cancelAnimationFrame(frame);
  }, [messages.length, activeSession?.id, activeDocument?.id]);

  async function createSession() {
    setBusy(true);
    try {
      const created = await request("/api/v1/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: `Phiên phân tích ${sessions.length + 1}` }) });
      setActiveSessionId(created.session.id); setActiveDocumentId(null); await refresh(created.session.id);
    } catch (error) { showNotice(error.message, "error"); } finally { setBusy(false); }
  }

  async function upload(file) {
    if (!file || !activeSession) return;
    if (file.size > 100 * 1024 * 1024) { showNotice("PDF vượt giới hạn 100 MiB.", "error"); return; }
    setBusy(true); showNotice("Đang upload và trích text từ PDF…");
    try {
      const form = new FormData(); form.append("file", file);
      const result = await request(`/api/v1/sessions/${activeSession.id}/documents`, { method: "POST", body: form });
      setActiveDocumentId(result.document.id); await refresh(activeSession.id);
      showNotice(`Đã lưu ${result.document.file_name} (${formatBytes(result.document.byte_size)}); extraction đang chạy nền.`);
    } catch (error) { showNotice(error.message, "error"); } finally { setBusy(false); if (uploadRef.current) uploadRef.current.value = ""; }
  }

  async function submitQuestion(questionInput) {
    const question = questionInput?.trim();
    if (!question || requestInFlightRef.current || busy || !activeDocument || activeDocument.extraction_status !== "ready" || !activeSession) return;
    requestInFlightRef.current = true;
    forceChatScrollRef.current = true;
    const userId = crypto.randomUUID();
    const pendingId = crypto.randomUUID();
    const scope = { session_id: activeSession.id, document_id: activeDocument.id };
    setPendingMessages((current) => [...current.filter((message) => !message.failed), { id: userId, role: "user", body: question, ...scope, pending: true }, { id: pendingId, role: "assistant", body: "", structured_answer: { pending: true }, ...scope, pending: true }]);
    setQuery(""); setRetryQuestion(""); setBusy(true); clearNotice();
    try {
      const result = await request(`/api/v1/sessions/${activeSession.id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_id: activeDocument.id, question }) });
      setPendingMessages((current) => current.filter((message) => message.id !== userId && message.id !== pendingId));
      try { await refresh(activeSession.id); }
      catch (refreshError) { showNotice(`Đã nhận câu trả lời nhưng chưa tải lại lịch sử: ${refreshError.message}`, "error"); }
      const firstCitation = result.assistant_message?.citations?.[0];
      if (firstCitation?.page) { setCitationPage(firstCitation.page); setCitationQuote(""); setCitationBbox(normalizedBbox(firstCitation.bbox)); }
    } catch (error) {
      setPendingMessages((current) => current.map((message) => message.id === pendingId ? { ...message, structured_answer: null, body: `Không thể tạo câu trả lời: ${error.message}`, pending: false, failed: true } : message));
      setRetryQuestion(question); showNotice(error.message, "error");
    } finally { requestInFlightRef.current = false; setBusy(false); }
  }

  async function ask(event) { event.preventDefault(); await submitQuestion(query); }

  async function openTrace(message) {
    const messageId = typeof message === "string" ? message : message?.id;
    if (!activeSession || !messageId) return;
    const selectedMessage = typeof message === "string" ? messages.find((item) => item.id === message) ?? null : message;
    const selectedIndex = selectedMessage ? messages.findIndex((item) => item.id === selectedMessage.id) : -1;
    const previousMessage = selectedIndex > 0 ? messages[selectedIndex - 1] : null;
    setTraceMessage(selectedMessage ? { ...selectedMessage, question: previousMessage?.role === "user" ? previousMessage.body : null } : null);
    setTraceBusy(true);
    try { setTraceData(await request(`/api/v1/sessions/${activeSession.id}/messages/${messageId}/trace`)); }
    catch (error) { showNotice(error.message, "error"); }
    finally { setTraceBusy(false); }
  }

  async function openEvidence() {
    if (!activeSession || !activeDocument || activeDocument.extraction_status !== "ready") return;
    setEvidenceBusy(true);
    try { setEvidenceData(await request(`/api/v1/sessions/${activeSession.id}/documents/${activeDocument.id}/evidences`)); }
    catch (error) { showNotice(error.message, "error"); }
    finally { setEvidenceBusy(false); }
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

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span>S</span><strong>SourceLens</strong></div><div className="breadcrumb">Workspace <b>/</b> {activeSession?.title ?? "Đang tải…"}</div><div className="top-actions"><button className="audit-button" disabled={!activeDocument || activeDocument.extraction_status !== "ready" || evidenceBusy} onClick={openEvidence}><Icon name="link" size={14} /> Dữ liệu</button><button className="audit-button" disabled={!latestAssistant || traceBusy} onClick={() => openTrace(latestAssistant)}><Icon name="trace" size={14} /> {traceData ? "Đang xem audit" : "Mở audit"}</button><span className="storage-pill">Local workspace</span><button className="upload-button" disabled={!activeSession || busy} onClick={() => uploadRef.current?.click()}><Icon name="upload" size={14} /> Tải PDF</button><input ref={uploadRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => upload(event.target.files?.[0])} /></div></header>
    <main className="workspace">
      <aside className="session-sidebar"><div className="session-heading"><div><small>WORKSPACE</small><h2>Phiên tài liệu</h2></div><button aria-label="Tạo phiên mới" title="Tạo phiên mới" onClick={createSession} disabled={busy}><Icon name="add" /></button></div><input className="session-search" aria-label="Tìm phiên hoặc tài liệu" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm phiên hoặc tài liệu…" />
        <div className="session-list">{booting && !sessions.length && <div className="session-loading" role="status">Đang tải workspace…</div>}{!booting && !filteredSessions.length && <div className="session-loading">Chưa có phiên phù hợp.</div>}{filteredSessions.map((session) => <section className={`session-item ${session.id === activeSession?.id ? "active" : ""}`} key={session.id}><button className="session-button" onClick={() => { setActiveSessionId(session.id); setActiveDocumentId(session.documents[0]?.id ?? null); }}><span className="session-icon"><Icon name="folder" size={14} /></span><span><b>{session.title}</b><small>{session.documents.length} tài liệu</small></span></button>{session.id === activeSession?.id && <div className="document-list">{session.documents.map((document) => <button key={document.id} className={document.id === activeDocument?.id ? "selected" : ""} onClick={() => setActiveDocumentId(document.id)}><span className="pdf-dot">PDF</span><span><b>{document.file_name}</b><small>{formatBytes(document.byte_size)} · {document.page_count ?? "?"} trang</small></span></button>)}{!session.documents.length && <button className="empty-document" onClick={() => uploadRef.current?.click()}><Icon name="add" size={13} /> Thêm PDF đầu tiên</button>}</div>}</section>)}</div>
        <div className="sidebar-note"><b>100 MiB / PDF</b><span>Binary và metadata được lưu local theo session.</span></div>
      </aside>
      <section className="reader-column"><PdfViewer document={activeDocument} sessionId={activeSession?.id} citationPage={citationPage} evidenceQuote={citationQuote} evidenceBbox={citationBbox} />{notice && <div className={`toast ${noticeKind}`} role={noticeKind === "error" ? "alert" : "status"} aria-live="polite"><span>{notice}</span>{retryQuestion && <button onClick={() => submitQuestion(retryQuestion)} disabled={busy}><Icon name="refresh" size={13} /> Thử lại</button>}<button className="toast-close" aria-label="Đóng thông báo" onClick={clearNotice}><Icon name="close" size={13} /></button></div>}</section>
      <aside className="chat-column"><header className="chat-header"><div className="ai-avatar">S</div><div><h2>Hỏi tài liệu</h2><span>{activeDocument ? activeDocument.file_name : "Chưa chọn tài liệu"}</span></div><span className="mode-badge">{modeLabel}</span></header><div className="chat-body">{!messages.length && <div className="welcome"><div className="welcome-mark"><Icon name="spark" size={18} /></div><h3>Tôi có thể giúp bạn tìm gì?</h3><p>Câu trả lời mặc định dùng retrieval xác định. Khi bật OpenRouter, câu trả lời có summary, claims, công thức, bảng và cảnh báo theo schema.</p>{activeDocument?.extraction_status === "ready" && <button onClick={() => setQuery("Tóm tắt nội dung chính của tài liệu")}>Tóm tắt nội dung chính</button>}</div>}{messages.map((message) => <article key={message.id} className={`message ${message.role}`}><span className="message-avatar">{message.role === "user" ? "B" : "S"}</span><div><small>{message.role === "user" ? "Bạn" : "SourceLens"}</small><StructuredAnswer answer={presentationAnswer(message)} fallback={message.body} onCitation={(page, quote, bbox) => { setCitationPage(page); setCitationQuote(quote); setCitationBbox(normalizedBbox(bbox)); }} />{message.needs_update && <div className="answer-status-note stale-answer"><Icon name="refresh" size={13} /><span>Dữ liệu đầu vào đã thay đổi; câu trả lời này cần tính lại.</span></div>}{message.citations?.map((citation, index) => <button className="citation" key={index} onClick={() => { setCitationPage(citation.page); setCitationQuote(""); setCitationBbox(normalizedBbox(citation.bbox)); }}><Icon name="link" size={12} /> Trang {citation.page}{citation.bbox ? " · bbox" : ""}</button>)}{message.role === "assistant" && !message.pending && !message.failed && <button className="trace-button" disabled={traceBusy} onClick={() => openTrace(message.id)}><Icon name="trace" size={12} /> {traceBusy ? "Đang đọc flow…" : "Data flow"}</button>}</div></article>)}{traceData && <div className="trace-panel"><div className="trace-panel-heading"><div><strong>Data flow audit</strong><small>{traceData.trace?.length ?? 0} events · trace_id {traceData.trace_id ?? "—"}</small></div><button aria-label="Đóng data flow" onClick={() => setTraceData(null)}><Icon name="close" size={14} /></button></div>{(traceData.trace ?? []).map((event, index) => <div className="trace-event" key={`${event.stage}-${index}`}><span className={`trace-dot ${event.status}`}></span><div><b>{event.stage}</b><small>{event.status} · {event.at}</small>{event.provider && <em>{event.provider}</em>}{event.pages && <em>trang: {event.pages.join(", ")}</em>}{event.scores && <em>score: {event.scores.join(", ")}</em>}{event.context_manifest && <em>context: {event.context_manifest.map((item) => `p${item.page} · ${item.chars} ký tự · ${item.text_sha256.slice(0, 10)}…`).join(" | ")}</em>}{event.citation_pages && <em>citation: ${event.citation_pages.join(", ")}</em>}</div></div>)}</div>}</div><form className="chat-composer" onSubmit={ask}><textarea aria-label="Câu hỏi về tài liệu" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={!activeDocument ? "Tải PDF để bắt đầu" : activeDocument.extraction_status === "ready" ? "Hỏi về tài liệu này…" : "Đang tạo text index…"} disabled={!activeDocument || activeDocument.extraction_status !== "ready" || busy} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} /><div><span>{activeDocument?.extraction_status === "ready" ? "Text index sẵn sàng" : activeDocument?.extraction_status === "queued" ? "Extraction đang chạy" : "Chưa có text index"}</span><button aria-label="Gửi câu hỏi" title="Gửi câu hỏi" disabled={!activeDocument || activeDocument.extraction_status !== "ready" || busy || !query.trim()}><Icon name="send" size={15} /></button></div></form></aside>
      <AuditDrawer traceData={traceData} traceMessage={traceMessage} activeDocument={activeDocument} onClose={() => { setTraceData(null); setTraceMessage(null); }} />
      <EvidenceDrawer data={evidenceData} busy={evidenceBusy} onClose={() => setEvidenceData(null)} onFocus={(evidence) => { setCitationPage(evidence.page_number); setCitationQuote(""); setCitationBbox(normalizedBbox(evidence.bbox)); }} onSave={saveEvidence} />
    </main>
  </div>;
}

export default App;
