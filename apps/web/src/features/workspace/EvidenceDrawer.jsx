import { useEffect, useId, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { Icon } from "./Icon.jsx";
import { dataStatusLabel, evidenceLabel, formatDateTime, formatNumber, numbersDiffer } from "./format.js";

const EDIT_ERROR_FALLBACK = "Không đọc được số này. Hãy nhập lại, ví dụ 21.500 hoặc 21500.";

// The API sends a Vietnamese message with every error code; an error without
// a code (e.g. a request-shape 422) gets a plain hint instead of "HTTP 422".
function editError(error) {
  if (error?.code && error.message) return error.message;
  if (!error?.message || /^HTTP \d+$/.test(error.message)) return EDIT_ERROR_FALLBACK;
  return error.message;
}

function isEdited(evidence) {
  return numbersDiffer(evidence.current_numeric_value, evidence.original_numeric_value);
}

function displayValue(evidence) {
  return formatNumber(evidence.current_numeric_value) || evidence.raw_text || "Chưa đọc được";
}

function RevisionHistory({ history }) {
  if (!history || history.loading) return <p className="evidence-history-note" role="status">Đang tải lịch sử…</p>;
  if (history.error) return <p className="evidence-history-note" role="alert">{history.error}</p>;
  return <ol className="evidence-history">
    {history.revisions.map((revision) => <li key={revision.id}>
      {revision.action === "edit"
        ? <span><b>{formatNumber(revision.old_numeric_value) || "trống"} → {formatNumber(revision.numeric_value)}</b>{revision.reason ? ` · ${revision.reason}` : ""}</span>
        : <span>{revision.action === "initialize" ? "Đọc từ PDF" : "Đọc lại"}: <b>{formatNumber(revision.numeric_value) || "chưa đọc được"}</b></span>}
      {revision.carried_over_from_revision_id && <em>giữ lại sau khi đọc lại tài liệu</em>}
      <time dateTime={revision.created_at}>{formatDateTime(revision.created_at)}</time>
    </li>)}
  </ol>;
}

function EditForm({ evidence, basePath, onCancel, onSaved, onConflict }) {
  const ids = useId();
  const [inputText, setInputText] = useState(evidence.current_numeric_value == null ? "" : formatNumber(evidence.current_numeric_value));
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  // Possible readings of an ambiguous number; the one the user picks is sent
  // as numeric_value instead of the typed text.
  const [readings, setReadings] = useState([]);
  const [chosenValue, setChosenValue] = useState(null);
  const [working, setWorking] = useState(false);
  const path = `${basePath}/evidences/${encodeURIComponent(evidence.evidence_key)}/revisions`;
  const post = (query = "", value = chosenValue) => request(`${path}${query}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(value == null ? { input_text: inputText.trim() } : { numeric_value: value }), reason: reason.trim(), expected_revision_id: evidence.current_revision_id }),
  });

  // Any change to the text invalidates the number we asked the user to confirm.
  const change = (setter) => (event) => { setter(event.target.value); setPreview(null); setError(""); setReadings([]); setChosenValue(null); };

  async function requestPreview(value) {
    setWorking(true); setError(""); setReadings([]);
    try { setPreview(await post("?dry_run=true", value)); setChosenValue(value); }
    catch (failure) {
      setError(editError(failure));
      if (failure?.code === "NUMBER_FORMAT_AMBIGUOUS") setReadings(failure.detail?.readings ?? []);
      if (failure?.code === "EVIDENCE_REVISION_CONFLICT") onConflict();
    }
    finally { setWorking(false); }
  }

  function check(event) { event.preventDefault(); requestPreview(null); }

  async function save() {
    setWorking(true); setError("");
    try { onSaved(evidence, await post()); }
    catch (failure) { setError(editError(failure)); setPreview(null); if (failure?.code === "EVIDENCE_REVISION_CONFLICT") onConflict(); }
    finally { setWorking(false); }
  }

  return <form className="evidence-edit-form" onSubmit={check} aria-label={`Sửa số ${evidenceLabel(evidence) || `trang ${evidence.page_number}`}`}>
    <label htmlFor={`${ids}-value`}>Giá trị mới</label>
    <input id={`${ids}-value`} autoFocus inputMode="decimal" value={inputText} onChange={change(setInputText)} required aria-invalid={Boolean(error)} aria-describedby={error ? `${ids}-error` : undefined} />
    <label htmlFor={`${ids}-reason`}>Lý do sửa</label>
    <textarea id={`${ids}-reason`} value={reason} onChange={change(setReason)} minLength="3" required placeholder="Ví dụ: Đối chiếu lại PDF gốc" />
    {error && <p className="evidence-edit-error" id={`${ids}-error`} role="alert">{error}</p>}
    {readings.length > 0 && <div className="evidence-edit-readings" role="group" aria-label="Chọn số bạn muốn lưu"><span>Ý bạn là:</span>{readings.map((reading) => <button type="button" key={reading} disabled={working} onClick={() => requestPreview(reading)}>{formatNumber(reading)}</button>)}</div>}
    {preview && <p className="evidence-edit-preview" role="status">Sẽ lưu: <b>{preview.display ?? formatNumber(preview.parsed_value)}</b></p>}
    <div>
      <button type="button" onClick={onCancel} disabled={working}>Hủy</button>
      {preview
        ? <button type="button" className="evidence-edit-primary" onClick={save} disabled={working}>{working ? "Đang lưu…" : "Xác nhận lưu"}</button>
        : <button type="submit" className="evidence-edit-primary" disabled={working}>{working ? "Đang kiểm tra…" : "Kiểm tra số"}</button>}
    </div>
  </form>;
}

export function EvidenceDrawer({ data, basePath, onClose, onFocus, onSaved, onReload }) {
  const [editingKey, setEditingKey] = useState(null);
  const [histories, setHistories] = useState({});
  const [openHistory, setOpenHistory] = useState(null);
  const drawerRef = useRef(null);
  const open = Boolean(data);

  // Focus moves into the drawer and back to whatever opened it.
  useEffect(() => {
    if (!open) return undefined;
    const opener = document.activeElement;
    drawerRef.current?.focus();
    return () => { if (opener instanceof HTMLElement && opener.isConnected) opener.focus(); };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    // Escape first leaves an open form, then closes the drawer.
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      if (editingKey) setEditingKey(null);
      else onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, editingKey, onClose]);

  if (!data) return null;

  async function toggleHistory(evidence) {
    const key = evidence.evidence_key;
    if (openHistory === key) { setOpenHistory(null); return; }
    setOpenHistory(key);
    setHistories((current) => ({ ...current, [key]: { loading: true } }));
    try {
      const result = await request(`${basePath}/evidences/${encodeURIComponent(key)}/revisions`);
      setHistories((current) => ({ ...current, [key]: { revisions: result.revisions ?? [] } }));
    } catch (error) {
      setHistories((current) => ({ ...current, [key]: { error: error?.message || "Không tải được lịch sử sửa." } }));
    }
  }

  return <section className="evidence-drawer" role="dialog" aria-labelledby="evidence-drawer-title" tabIndex={-1} ref={drawerRef}>
    <header className="audit-drawer-header"><div><span className="audit-kicker">DỮ LIỆU SỐ</span><h3 id="evidence-drawer-title">Số liệu trong tài liệu</h3><small>Bấm vào một số để xem vị trí trong PDF. Giá trị gốc luôn được giữ lại khi sửa.</small></div><button type="button" aria-label="Đóng dữ liệu" onClick={onClose}><Icon name="close" size={15} /></button></header>
    <div className="evidence-drawer-body">{data.evidences?.length ? data.evidences.map((evidence) => {
      const label = evidenceLabel(evidence);
      const name = label || `số ở trang ${evidence.page_number}`;
      const edited = isEdited(evidence);
      const status = edited ? "" : dataStatusLabel(evidence.data_status);
      const hasHistory = (evidence.revision_count ?? 0) > 1;
      return <article className="evidence-record" key={evidence.evidence_key}>
        <button type="button" className="evidence-record-main" onClick={() => onFocus(evidence)} aria-label={`${name}: ${displayValue(evidence)}, trang ${evidence.page_number}. Mở vị trí trong PDF`}>
          <span>Trang {evidence.page_number} · {evidence.method_label}</span>
          <b>{displayValue(evidence)}</b>
          <small className="evidence-record-label">{label || "Số trong văn bản, chưa có nhãn"}</small>
          {edited && <small>Đã sửa · số gốc trong PDF: {formatNumber(evidence.original_numeric_value) || evidence.raw_text}</small>}
          {status && <small className="evidence-record-status">{status}</small>}
        </button>
        {editingKey === evidence.evidence_key
          ? <EditForm evidence={evidence} basePath={basePath} onCancel={() => setEditingKey(null)} onConflict={onReload} onSaved={(item, result) => { setEditingKey(null); setOpenHistory(null); onSaved(item, result); }} />
          : <div className="evidence-record-actions">
            <button type="button" className="evidence-edit-button" onClick={() => setEditingKey(evidence.evidence_key)} aria-label={`Sửa số: ${name}`}>Sửa số</button>
            {hasHistory && <button type="button" className="evidence-history-button" aria-expanded={openHistory === evidence.evidence_key} onClick={() => toggleHistory(evidence)}>{openHistory === evidence.evidence_key ? "Ẩn lịch sử sửa" : "Lịch sử sửa"}</button>}
          </div>}
        {openHistory === evidence.evidence_key && <RevisionHistory history={histories[evidence.evidence_key]} />}
      </article>;
    }) : <p className="evidence-empty">Tài liệu này chưa có số liệu để sửa.</p>}</div>
  </section>;
}
