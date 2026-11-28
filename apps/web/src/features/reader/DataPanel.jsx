import { useEffect, useId, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { dataStatusLabel, differsFromReading, evidenceLabel, formatNumber, needsCheck } from "./format.js";
import { checkTableTotals, formatNumber as formatValue } from "./reportChecks.js";

/**
 * What a corrected value would do to the total check of its column, said
 * against how the column stands now: "vẫn khớp", "sẽ khớp", "sẽ lệch", "vẫn lệch".
 */
export function totalImpact(all, evidence, value) {
  const locator = evidence.table_locator;
  if (!locator?.table_region_key || value == null || value === "") return "";
  const column = all.filter((item) => item.table_locator?.table_region_key === locator.table_region_key && item.table_locator?.column_index === locator.column_index);
  const checkOf = (cells) => checkTableTotals(cells).find((check) => check.keys.includes(evidence.evidence_key));
  const before = checkOf(column);
  const after = checkOf(column.map((item) => item.evidence_key === evidence.evidence_key ? { ...item, current_numeric_value: String(value) } : item));
  if (!after) return "";
  const gap = formatValue(Math.abs(after.diff));
  if (after.ok) return before && !before.ok ? "Tổng cột sẽ khớp" : "Tổng cột vẫn khớp";
  return before && !before.ok ? `Tổng cột vẫn lệch ${gap}` : `Tổng cột sẽ lệch ${gap}`;
}

// Wait for a pause in typing before asking the server how it reads the number.
const PREVIEW_DELAY_MS = 400;

/**
 * The number that will be saved. When the server read the typed text in a
 * way the reader may not expect ("21,500" in a report that writes 21.500),
 * it adds the plain digits so 1.250 (one thousand two hundred fifty) is never read as 1,25.
 */
export function previewText(preview, typed = "") {
  const value = String(preview.plain_value ?? preview.parsed_value ?? "");
  const shown = formatNumber(value);
  const plain = value.replace(".", ",");
  const input = String(typed).replace(/\s+/g, "");
  if (!plain || plain === shown || input === shown || input === plain) return shown;
  return `${shown} (= ${plain})`;
}

/**
 * The numbers with one saved correction applied, so every view shows the
 * new value at once instead of after the next fetch.
 */
export function withSavedRevision(data, evidenceKey, result) {
  const revision = result?.revision;
  if (!data?.evidences || !revision?.id) return data;
  return {
    ...data,
    data_revision: result.data_revision ?? data.data_revision,
    evidences: data.evidences.map((item) => item.evidence_key !== evidenceKey ? item : {
      ...item,
      current_numeric_value: revision.numeric_value,
      current_revision_id: revision.id,
      revision_count: (item.revision_count ?? 1) + 1,
      // The server counts a corrected number as valid.
      data_status: "valid",
    }),
  };
}

/**
 * Correct one number. The server reads the typed text in the report's own
 * number format; a dry run, run while typing, shows what will be saved.
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
  const timer = useRef(null);
  // Bumped on every keystroke: a preview that comes back for older text is dropped.
  const generation = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const path = `${basePath}/evidences/${encodeURIComponent(evidence.evidence_key)}/revisions`;
  const post = (query, input, value) => request(`${path}${query}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(value == null ? { input_text: input.trim() } : { numeric_value: value }), reason: reason.trim(), expected_revision_id: evidence.current_revision_id }),
  });
  const fail = (failure) => {
    setError(failure.message);
    if (failure?.code === "NUMBER_FORMAT_AMBIGUOUS") setReadings(failure.detail?.readings ?? []);
    if (failure?.code === "EVIDENCE_REVISION_CONFLICT") onConflict();
  };
  async function check(input, value = null) {
    const own = ++generation.current;
    setError(""); setReadings([]);
    try {
      const result = await post("?dry_run=true", input, value);
      if (own !== generation.current) return null;
      setPreview(result); setChosen(value);
      return result;
    } catch (failure) { if (own === generation.current) fail(failure); return null; }
  }
  const onType = (next) => {
    setText(next);
    window.clearTimeout(timer.current);
    generation.current += 1;
    setPreview(null); setReadings([]); setChosen(null); setError("");
    if (next.trim()) timer.current = window.setTimeout(() => check(next), PREVIEW_DELAY_MS);
  };
  async function save(value) {
    setWorking(true); setError("");
    try { onSaved(evidence, await post("", text, value)); } catch (failure) { setPreview(null); fail(failure); } finally { setWorking(false); }
  }
  async function submit() {
    if (working) return;
    if (!text.trim()) { setError("Nhập số"); return; }
    window.clearTimeout(timer.current);
    if (preview) { save(chosen); return; }
    setWorking(true);
    const checked = await check(text);
    setWorking(false);
    if (checked) save(null);
  }
  const impact = preview ? totalImpact(all, evidence, preview.plain_value ?? preview.parsed_value) : "";
  return <form className="rd-edit" onSubmit={(event) => { event.preventDefault(); submit(); }} noValidate>
    <b>{evidenceLabel(evidence) || `Số ở trang ${evidence.page_number}`}</b>
    <label htmlFor={`${ids}-v`}>Số đúng</label>
    <input id={`${ids}-v`} className="rd-input" autoFocus inputMode="decimal" maxLength={80} value={text} onChange={(event) => onType(event.target.value)} />
    <label htmlFor={`${ids}-r`}>Ghi chú (không bắt buộc)</label>
    <input id={`${ids}-r`} className="rd-input" maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} />
    {readings.length > 0 && <div className="rd-readings" role="group" aria-label="Chọn số để lưu"><span>Ý bạn là:</span>{readings.map((reading) => <button type="button" key={reading} disabled={working} onClick={() => check(text, reading)}>{formatNumber(reading)}</button>)}</div>}
    {preview && <p className="rd-preview" role="status">Sẽ đổi: <b>{formatNumber(evidence.current_numeric_value) || "—"} → {previewText(preview, text)}</b>{impact && <small>{impact}</small>}{preview.decimal_separator && preview.decimal_separator !== "," ? <small>Báo cáo này dùng dấu “{preview.decimal_separator}” làm dấu thập phân.</small> : null}</p>}
    {error && <p className="rd-error-text" role="alert">{error}</p>}
    <div className="rd-actions">
      <button type="submit" className="rd-button primary" disabled={working}>Lưu</button>
      <button type="button" onClick={onCancel}>Hủy</button>
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
    {revision.action === "initialize"
      ? <span>Gốc: <b>{formatNumber(revision.numeric_value) || "—"}</b></span>
      : revision.action === "edit" || revision.reason
      ? <span><b>{formatNumber(revision.old_numeric_value) || "—"} → {formatNumber(revision.numeric_value)}</b>{revision.reason ? ` · ${revision.reason}` : ""}</span>
      : <span>Đọc lại: <b>{formatNumber(revision.numeric_value) || "—"}</b></span>}
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
  const list = onlyTables ? all.filter((evidence) => evidence.table_locator || evidence.chart_read) : all;
  const numbers = list.filter((evidence) => evidence.current_numeric_value != null).length;
  const pages = [...new Set(list.map((evidence) => evidence.page_number))].sort((a, b) => a - b);
  return <aside className="rd-panel" role="dialog" aria-modal="true" aria-label="Số liệu">
    <header><div><h2>Số liệu</h2><p>{numbers} số</p></div><button type="button" className="rd-icon-button" aria-label="Đóng" onClick={onClose}>×</button></header>
    <label className="rd-toggle"><input type="checkbox" checked={onlyTables} onChange={(event) => setOnlyTables(event.target.checked)} /> Chỉ bảng</label>
    <div className="rd-panel-body">
      {loading && <div className="rd-skeleton-lines"><i /><i /><i /><i /></div>}
      {!loading && !list.length && <p className="rd-small">Không có số nào</p>}
      {pages.map((page) => <section key={page}><h3>Trang {page}</h3><ul>{list.filter((evidence) => evidence.page_number === page).map((evidence) => {
        const label = evidenceLabel(evidence) || `Số ở trang ${evidence.page_number}`;
        const edited = differsFromReading(evidence.current_numeric_value, evidence.original_numeric_value);
        const status = edited ? "" : dataStatusLabel(evidence.data_status);
        const shown = evidence.current_numeric_value != null ? formatNumber(evidence.current_numeric_value) : "—";
        return <li key={evidence.evidence_key} className={needsCheck(evidence.data_status) && !edited ? "unsure" : ""}>
          {editing === evidence.evidence_key
            ? <EditForm evidence={evidence} all={all} basePath={basePath} onCancel={() => setEditing(null)} onConflict={onReload} onSaved={(item, result) => { setEditing(null); onSaved(item, result); }} />
            : <div className="rd-data-item">
              <div className="rd-data-line">
                <button type="button" className="rd-data-row" onClick={() => onFocus({ page: evidence.page_number, boxes: evidence.bbox ? [evidence.bbox] : [], label, value: shown, raw: evidence.raw_text, key: evidence.evidence_key, unsure: needsCheck(evidence.data_status) })}>
                  <span>{label}</span>
                  <b>{shown}</b>
                </button>
                <button type="button" className="rd-link" onClick={() => { setEditing(evidence.evidence_key); setHistory(null); onFocus({ page: evidence.page_number, boxes: evidence.bbox ? [evidence.bbox] : [], label, value: shown, raw: evidence.raw_text, key: evidence.evidence_key }); }}>Sửa</button>
              </div>
              {(edited || status || evidence.revision_count > 1) && <div className="rd-data-meta">
                {edited && <small>Đã sửa · gốc {formatNumber(evidence.original_numeric_value) || evidence.raw_text}</small>}
                {!edited && evidence.current_numeric_value == null && evidence.raw_text && evidence.data_status !== "missing" && <small>PDF ghi “{evidence.raw_text}”</small>}
                {status && <small className={needsCheck(evidence.data_status) ? "warn" : ""}>{status}</small>}
                {evidence.revision_count > 1 && <button type="button" className="rd-link" aria-expanded={history === evidence.evidence_key} onClick={() => setHistory(history === evidence.evidence_key ? null : evidence.evidence_key)}>Lịch sử</button>}
              </div>}
              {history === evidence.evidence_key && <History basePath={basePath} evidence={evidence} />}
            </div>}
        </li>;
      })}</ul></section>)}
    </div>
  </aside>;
}
