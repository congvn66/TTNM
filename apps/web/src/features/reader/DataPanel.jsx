import { useEffect, useId, useState } from "react";
import { request } from "../../shared/api/client.js";
import { dataStatusLabel, differsFromReading, evidenceLabel, formatNumber, needsCheck } from "./format.js";
import { checkTableTotals, formatNumber as formatValue } from "./reportChecks.js";

/** What a corrected value would do to the total check of its column. */
function totalImpact(all, evidence, value) {
  const locator = evidence.table_locator;
  if (!locator?.table_region_key || value == null || value === "") return "";
  const column = all.filter((item) => item.table_locator?.table_region_key === locator.table_region_key && item.table_locator?.column_index === locator.column_index);
  const after = checkTableTotals(column.map((item) => item.evidence_key === evidence.evidence_key ? { ...item, current_numeric_value: String(value) } : item)).find((check) => check.keys.includes(evidence.evidence_key));
  if (!after) return "";
  return after.ok ? "Dòng tổng của cột này vẫn khớp." : `Dòng tổng của cột này sẽ lệch ${formatValue(Math.abs(after.diff))}.`;
}

const REASON_MIN = 3;

/** "21.500 (= 21500)" so 1.250 (one thousand two hundred fifty) is never read as 1,25. */
function previewText(preview) {
  const value = String(preview.plain_value ?? preview.parsed_value ?? "");
  const shown = formatNumber(value);
  const plain = value.replace(".", ",");
  return plain && plain !== shown ? `${shown} (= ${plain})` : shown;
}

/**
 * Correct one number. The server reads the typed text in the report's own
 * number format; a dry run shows what will be saved before it is saved.
 */
export function EditForm({ evidence, all, basePath, onCancel, onSaved, onConflict }) {
  const ids = useId();
  const [text, setText] = useState(evidence.current_numeric_value == null ? "" : formatNumber(evidence.current_numeric_value));
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState(null);
  const [readings, setReadings] = useState([]);
  const [chosen, setChosen] = useState(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const path = `${basePath}/evidences/${encodeURIComponent(evidence.evidence_key)}/revisions`;
  const post = (query, value) => request(`${path}${query}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(value == null ? { input_text: text.trim() } : { numeric_value: value }), reason: reason.trim(), expected_revision_id: evidence.current_revision_id }),
  });
  const reset = () => { setPreview(null); setReadings([]); setChosen(null); setError(""); };
  const fail = (failure) => {
    setError(failure.message);
    if (failure?.code === "NUMBER_FORMAT_AMBIGUOUS") setReadings(failure.detail?.readings ?? []);
    if (failure?.code === "EVIDENCE_REVISION_CONFLICT") onConflict();
  };
  async function check(value = null) {
    if (!text.trim()) { setError("Hãy nhập số đúng."); return; }
    if (reason.trim().length < REASON_MIN) { setError(`Hãy ghi lý do sửa, ít nhất ${REASON_MIN} ký tự.`); return; }
    setWorking(true); setError(""); setReadings([]);
    try { setPreview(await post("?dry_run=true", value)); setChosen(value); } catch (failure) { fail(failure); } finally { setWorking(false); }
  }
  async function save() {
    setWorking(true); setError("");
    try { onSaved(evidence, await post("", chosen)); } catch (failure) { setPreview(null); fail(failure); } finally { setWorking(false); }
  }
  return <form className="rd-edit" onSubmit={(event) => { event.preventDefault(); if (preview) save(); else check(); }} noValidate>
    <b>{evidenceLabel(evidence) || `Số ở trang ${evidence.page_number}`}</b>
    <label htmlFor={`${ids}-v`}>Số đúng</label>
    <input id={`${ids}-v`} className="rd-input" autoFocus inputMode="decimal" maxLength={80} value={text} onChange={(event) => { setText(event.target.value); reset(); }} />
    <label htmlFor={`${ids}-r`}>Vì sao sửa (bắt buộc)</label>
    <input id={`${ids}-r`} className="rd-input" maxLength={1000} value={reason} onChange={(event) => { setReason(event.target.value); reset(); }} placeholder="Ví dụ: đối chiếu lại PDF" />
    {readings.length > 0 && <div className="rd-readings" role="group" aria-label="Chọn số bạn muốn lưu"><span>Ý bạn là:</span>{readings.map((reading) => <button type="button" key={reading} disabled={working} onClick={() => check(reading)}>{formatNumber(reading)}</button>)}</div>}
    {preview && <p className="rd-preview" role="status">Sẽ đổi: <b>{formatNumber(evidence.current_numeric_value) || "—"} → {previewText(preview)}</b>{totalImpact(all, evidence, preview.plain_value ?? preview.parsed_value) && <small>{totalImpact(all, evidence, preview.plain_value ?? preview.parsed_value)}</small>}{preview.decimal_separator && preview.decimal_separator !== "," ? <small>Báo cáo này dùng dấu “{preview.decimal_separator}” làm dấu thập phân.</small> : null}</p>}
    {error && <p className="rd-error-text" role="alert">{error}</p>}
    <div className="rd-actions">
      <button type="submit" className="rd-button primary" disabled={working}>{preview ? "Lưu" : "Kiểm tra"}</button>
      <button type="button" onClick={onCancel}>Huỷ</button>
    </div>
  </form>;
}

function History({ basePath, evidence }) {
  const [state, setState] = useState({ loading: true, revisions: [], error: "" });
  useEffect(() => {
    let live = true;
    request(`${basePath}/evidences/${encodeURIComponent(evidence.evidence_key)}/revisions`)
      .then((result) => { if (live) setState({ loading: false, revisions: result.revisions ?? [], error: "" }); })
      .catch((failure) => { if (live) setState({ loading: false, revisions: [], error: failure.message }); });
    return () => { live = false; };
  }, [basePath, evidence.evidence_key, evidence.current_revision_id]);
  if (state.loading) return <p className="rd-small">Đang tải lịch sử…</p>;
  if (state.error) return <p className="rd-error-text">{state.error}</p>;
  return <ol className="rd-history">{state.revisions.map((revision) => <li key={revision.id}>
    {revision.action === "edit" || revision.reason
      ? <span><b>{formatNumber(revision.old_numeric_value) || "chưa có số"} → {formatNumber(revision.numeric_value)}</b>{revision.reason ? ` · ${revision.reason}` : ""}</span>
      : <span>{revision.action === "initialize" ? "Đọc từ PDF" : "Đọc lại"}: <b>{formatNumber(revision.numeric_value) || "chưa đọc được"}</b></span>}
  </li>)}</ol>;
}

/** Every number the app read, with a way to correct one. */
export function DataPanel({ open, data, loading, basePath, onClose, onFocus, onSaved, onReload }) {
  const [editing, setEditing] = useState(null);
  const [history, setHistory] = useState(null);
  const [onlyTables, setOnlyTables] = useState(true);
  useEffect(() => {
    setEditing(null); setHistory(null);
    if (!open) return undefined;
    const opener = document.activeElement;
    return () => { if (opener instanceof HTMLElement && document.contains(opener)) opener.focus(); };
  }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  const all = data?.evidences ?? [];
  const hasCharts = all.some((evidence) => evidence.chart_read);
  const where = hasCharts ? "bảng và biểu đồ" : "bảng";
  const list = onlyTables ? all.filter((evidence) => evidence.table_locator || evidence.chart_read) : all;
  const numbers = list.filter((evidence) => evidence.current_numeric_value != null).length;
  const pages = [...new Set(list.map((evidence) => evidence.page_number))].sort((a, b) => a - b);
  return <aside className="rd-panel" role="dialog" aria-modal="true" aria-label="Số liệu đã đọc">
    <header><div><h2>Số liệu đã đọc</h2><p>{numbers} số{onlyTables ? ` trong ${where}` : " trong cả báo cáo"}. Chạm để xem trên trang, sửa nếu đọc sai.</p></div><button type="button" className="rd-icon-button" aria-label="Đóng" onClick={onClose}>×</button></header>
    <label className="rd-toggle"><input type="checkbox" checked={onlyTables} onChange={(event) => setOnlyTables(event.target.checked)} /> Chỉ số trong {where}</label>
    <div className="rd-panel-body">
      {loading && <div className="rd-skeleton-lines"><i /><i /><i /><i /></div>}
      {!loading && !list.length && <p className="rd-small">Chưa có số nào{onlyTables ? " trong bảng. Bỏ chọn ô trên để xem cả số trong đoạn văn." : "."}</p>}
      {pages.map((page) => <section key={page}><h3>Trang {page}</h3><ul>{list.filter((evidence) => evidence.page_number === page).map((evidence) => {
        const label = evidenceLabel(evidence);
        const edited = differsFromReading(evidence.current_numeric_value, evidence.original_numeric_value);
        const status = edited ? "" : dataStatusLabel(evidence.data_status);
        const shown = evidence.current_numeric_value != null ? formatNumber(evidence.current_numeric_value) : "—";
        return <li key={evidence.evidence_key} className={needsCheck(evidence.data_status) && !edited ? "unsure" : ""}>
          {editing === evidence.evidence_key
            ? <EditForm evidence={evidence} all={all} basePath={basePath} onCancel={() => setEditing(null)} onConflict={onReload} onSaved={(item, result) => { setEditing(null); onSaved(item, result); }} />
            : <div className="rd-data-item">
              <div className="rd-data-line">
                <button type="button" className="rd-data-row" onClick={() => onFocus({ page: evidence.page_number, boxes: evidence.bbox ? [evidence.bbox] : [], label: label || evidence.method_label, value: shown, raw: evidence.raw_text, key: evidence.evidence_key, unsure: needsCheck(evidence.data_status) })}>
                  <span>{label || <em>{evidence.method_label}</em>}</span>
                  <b>{shown}</b>
                </button>
                <button type="button" className="rd-link" onClick={() => { setEditing(evidence.evidence_key); setHistory(null); onFocus({ page: evidence.page_number, boxes: evidence.bbox ? [evidence.bbox] : [], label: label || evidence.method_label, value: shown, raw: evidence.raw_text, key: evidence.evidence_key }); }}>Sửa</button>
              </div>
              {(edited || status || evidence.revision_count > 1) && <div className="rd-data-meta">
                {edited && <small>Đã sửa · số gốc trong PDF: {formatNumber(evidence.original_numeric_value) || evidence.raw_text}</small>}
                {!edited && evidence.current_numeric_value == null && evidence.raw_text && evidence.data_status !== "missing" && <small>Đã đọc được chữ: “{evidence.raw_text}”</small>}
                {status && <small className={needsCheck(evidence.data_status) ? "warn" : ""}>{status}</small>}
                {evidence.revision_count > 1 && <button type="button" className="rd-link" onClick={() => setHistory(history === evidence.evidence_key ? null : evidence.evidence_key)}>{history === evidence.evidence_key ? "Ẩn lịch sử" : "Lịch sử sửa"}</button>}
              </div>}
              {history === evidence.evidence_key && <History basePath={basePath} evidence={evidence} />}
            </div>}
        </li>;
      })}</ul></section>)}
    </div>
  </aside>;
}
