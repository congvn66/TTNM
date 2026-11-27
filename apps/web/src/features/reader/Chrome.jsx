import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { StatusDot, statusText, when } from "./Home.jsx";

function useDismiss(open, close, refs) {
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event) => { if (!refs.some((ref) => ref.current?.contains(event.target))) close(); };
    const onKey = (event) => { if (event.key === "Escape") close(); };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onPointer); document.removeEventListener("keydown", onKey); };
  }, [open, close, refs]);
}

function ReportSwitcher({ reports, selected, onOpen, onNew }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const buttonRef = useRef(null);
  const panelRef = useRef(null);
  useDismiss(open, () => setOpen(false), [buttonRef, panelRef]);
  const shown = reports.filter((report) => report.file_name.toLowerCase().includes(query.trim().toLowerCase()));
  return <div className="rd-switcher">
    <button ref={buttonRef} type="button" className="rd-switch-button" aria-expanded={open} aria-haspopup="listbox" aria-label={`Báo cáo đang mở: ${selected?.file_name ?? "chưa chọn"}. Bấm để đổi báo cáo`} onClick={() => setOpen((value) => !value)}>
      {selected && <StatusDot report={selected} />}
      <span><b>{selected?.file_name ?? "Chọn báo cáo"}</b>{selected && <small>{selected.page_count ? `${selected.page_count} trang · ` : ""}{statusText(selected)}</small>}</span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
    </button>
    {open && <div ref={panelRef} className="rd-popover rd-switch-panel" role="dialog" aria-label="Chọn báo cáo">
      {reports.length > 5 && <input autoFocus className="rd-input" placeholder="Tìm báo cáo…" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Tìm báo cáo" />}
      <ul role="listbox" aria-label="Báo cáo">{shown.map((report) => <li key={report.id}><button type="button" role="option" aria-selected={report.id === selected?.id} onClick={() => { onOpen(report.id); setOpen(false); }}>
        <StatusDot report={report} /><span><b>{report.file_name}</b><small>{report.page_count ? `${report.page_count} trang · ` : ""}{statusText(report)}{when(report.created_at) ? ` · ${when(report.created_at)}` : ""}</small></span>
      </button></li>)}</ul>
      <button type="button" className="rd-switch-new" onClick={() => { setOpen(false); onNew(); }}>+ Tải lên báo cáo mới</button>
    </div>}
  </div>;
}

function Menu({ items }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef(null);
  const panelRef = useRef(null);
  useDismiss(open, () => setOpen(false), [buttonRef, panelRef]);
  return <div className="rd-menu">
    <button ref={buttonRef} type="button" className="rd-icon-button" aria-label="Thêm tuỳ chọn" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((value) => !value)}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></svg>
    </button>
    {open && <div ref={panelRef} className="rd-popover rd-menu-panel" role="menu">
      {items.filter(Boolean).map((item) => item.section
        ? <p key={`section-${item.section}`} className="rd-menu-section" role="presentation">{item.section}</p>
        : item.choices
          ? <div key={item.label} className="rd-segment" role="group" aria-label={item.label}><span>{item.label}</span><div>{item.choices.map((choice) => <button key={choice.value} type="button" role="menuitemradio" aria-checked={choice.active} className={choice.active ? "active" : ""} onClick={() => item.onPick(choice.value)}>{choice.label}</button>)}</div></div>
          : <button key={item.label} type="button" role="menuitem" disabled={item.disabled} className={item.danger ? "danger" : ""} onClick={() => { setOpen(false); item.onClick(); }}>
            <span>{item.label}</span>{item.hint && <small>{item.hint}</small>}
          </button>)}
    </div>}
  </div>;
}

export function TopBar({ reports, selected, onHome, onOpen, onNew, onHelp, menuItems }) {
  return <header className="rd-top">
    <button type="button" className="rd-brand" onClick={onHome} aria-label="Về trang đầu">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M16 16l5 5" /><path d="M8 11h6" /></svg>
      <span>SourceLens</span>
    </button>
    {selected && <ReportSwitcher reports={reports} selected={selected} onOpen={onOpen} onNew={onNew} />}
    <div className="rd-top-actions">
      {selected && <button type="button" className="rd-button" onClick={onNew}>Tải lên báo cáo</button>}
      <button type="button" className="rd-icon-button" aria-label="Hướng dẫn" onClick={onHelp}>?</button>
      <Menu items={menuItems} />
    </div>
  </header>;
}

export function Toasts({ toasts, onClose }) {
  return <div className="rd-toasts" aria-live="polite">{toasts.map((toast) => <div key={toast.id} className={`rd-toast ${toast.kind ?? ""}`} role={toast.kind === "error" ? "alert" : "status"}>
    {toast.kind === "ready" && <span className="rd-toast-check" aria-hidden="true">✓</span>}
    <p>{toast.text}</p>
    {toast.action && <button type="button" onClick={() => { toast.action.onClick(); onClose(toast.id); }}>{toast.action.label}</button>}
    <button type="button" className="rd-toast-close" aria-label="Đóng" onClick={() => onClose(toast.id)}>×</button>
  </div>)}</div>;
}

export function DropOverlay({ onFile }) {
  const [active, setActive] = useState(false);
  const depth = useRef(0);
  useEffect(() => {
    const hasFile = (event) => [...(event.dataTransfer?.types ?? [])].includes("Files");
    const enter = (event) => { if (!hasFile(event)) return; depth.current += 1; setActive(true); };
    const leave = () => { depth.current = Math.max(0, depth.current - 1); if (!depth.current) setActive(false); };
    const over = (event) => { if (hasFile(event)) event.preventDefault(); };
    const drop = (event) => { if (!hasFile(event)) return; event.preventDefault(); depth.current = 0; setActive(false); onFile(event.dataTransfer.files?.[0]); };
    window.addEventListener("dragenter", enter); window.addEventListener("dragleave", leave); window.addEventListener("dragover", over); window.addEventListener("drop", drop);
    return () => { window.removeEventListener("dragenter", enter); window.removeEventListener("dragleave", leave); window.removeEventListener("dragover", over); window.removeEventListener("drop", drop); };
  }, [onFile]);
  if (!active) return null;
  return <div className="rd-drop-overlay" aria-hidden="true"><div><b>Thả để tải báo cáo lên</b><small>Chỉ nhận tệp PDF</small></div></div>;
}

export function HelpDialog({ open, onClose, onTour, canTour }) {
  const closeRef = useRef(null);
  useEffect(() => { if (open) closeRef.current?.focus(); }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return <div className="rd-modal-back" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="rd-modal" role="dialog" aria-modal="true" aria-labelledby="rd-help-title">
      <h2 id="rd-help-title">Cách dùng SourceLens</h2>
      <ol className="rd-how vertical">
        <li><span>1</span><div><b>Tải báo cáo PDF lên</b><p>Kéo thả vào bất cứ đâu trên màn hình. Đọc xong sẽ có tiếng chuông và thông báo.</p></div></li>
        <li><span>2</span><div><b>Hỏi bằng tiếng Việt</b><p>Hỏi một con số, so sánh, hay phần trăm thay đổi. Thẻ “Tóm tắt” có sẵn vài câu gợi ý.</p></div></li>
        <li><span>3</span><div><b>Chạm số màu xanh để tự kiểm</b><p>Ô số gốc tô vàng trên trang, hàng và cột của nó tô nhạt. Viền nét đứt là số mình chưa chắc.</p></div></li>
      </ol>
      <h3>Phím tắt</h3>
      <dl className="rd-keys"><div><dt><kbd>/</kbd></dt><dd>Đặt câu hỏi</dd></div><div><dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Trang trước, trang sau</dd></div><div><dt><kbd>Esc</kbd></dt><dd>Tắt đánh dấu trên trang</dd></div><div><dt><kbd>?</kbd></dt><dd>Mở hướng dẫn này</dd></div></dl>
      <div className="rd-modal-actions">{canTour && <button type="button" className="rd-button" onClick={() => { onClose(); onTour(); }}>Xem hướng dẫn từng bước</button>}<button ref={closeRef} type="button" className="rd-button primary" onClick={onClose}>Đã hiểu</button></div>
    </section>
  </div>;
}

const TOUR = [
  { target: "page", title: "Đây là báo cáo của bạn", text: "Trang PDF gốc luôn ở giữa. Số nào mình dùng để trả lời sẽ được tô ngay trên trang." },
  { target: "briefing", title: "Mình đã kiểm tra giúp bạn", text: "Thẻ Tóm tắt cho biết các dòng tổng có khớp không, và gợi ý vài câu để hỏi." },
  { target: "ask", title: "Hỏi ở đây", text: "Gõ câu hỏi bằng tiếng Việt rồi nhấn Enter. Trong câu trả lời, chạm số màu xanh để thấy nó trên trang." },
];

export function Tour({ step, onNext, onClose, onFinish }) {
  const [rect, setRect] = useState(null);
  const current = TOUR[step];
  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useLayoutEffect(() => {
    if (!current) return undefined;
    const measure = () => {
      const node = document.querySelector(`[data-tour="${current.target}"]`);
      setRect(node ? node.getBoundingClientRect() : null);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [current]);
  if (!current) return null;
  const width = 300;
  const style = rect
    ? { width, top: Math.min(window.innerHeight - 200, Math.max(12, rect.top + (current.target === "ask" ? -170 : current.target === "page" ? rect.height / 3 : 24))), left: Math.min(window.innerWidth - width - 12, Math.max(12, current.target === "page" ? rect.left + rect.width / 2 - width / 2 : rect.left - width - 16 > 12 ? rect.left - width - 16 : rect.left + 12)) }
    : { width, top: 80, left: 24 };
  return <>
    {rect && <svg className="rd-tour-dim" width="100%" height="100%" aria-hidden="true">
      <defs><mask id="rd-tour-hole"><rect width="100%" height="100%" fill="white" /><rect x={rect.left - 6} y={rect.top - 6} width={rect.width + 12} height={rect.height + 12} rx="14" fill="black" /></mask></defs>
      <rect width="100%" height="100%" mask="url(#rd-tour-hole)" />
      <rect className="rd-tour-ring" x={rect.left - 6} y={rect.top - 6} width={rect.width + 12} height={rect.height + 12} rx="14" />
    </svg>}
    <section className="rd-tour" style={style} role="dialog" aria-label={current.title}>
      <span className="rd-kicker">Bước {step + 1} / {TOUR.length}</span>
      <h3>{current.title}</h3>
      <p>{current.text}</p>
      <div className="rd-modal-actions">{step + 1 < TOUR.length && <button type="button" className="rd-link" onClick={onClose}>Bỏ qua</button>}<button type="button" className="rd-button primary" onClick={step + 1 < TOUR.length ? onNext : onFinish} autoFocus>{step + 1 < TOUR.length ? "Tiếp" : "Bắt đầu hỏi"}</button></div>
    </section>
  </>;
}
export const TOUR_LENGTH = TOUR.length;

export function RenameDialog({ report, onClose, onSave }) {
  const [name, setName] = useState(() => (report?.file_name ?? "").replace(/\.pdf$/i, ""));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!report) return null;
  const submit = async (event) => {
    event.preventDefault();
    if (!name.trim()) { setError("Hãy nhập tên báo cáo."); return; }
    setSaving(true); setError("");
    try { await onSave(report, `${name.trim()}.pdf`); onClose(); } catch (failure) { setError(failure.message); } finally { setSaving(false); }
  };
  return <div className="rd-modal-back" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="rd-modal" role="dialog" aria-modal="true" aria-labelledby="rd-rename-title" onSubmit={submit}>
      <h2 id="rd-rename-title">Đổi tên báo cáo</h2>
      <label className="rd-field">Tên mới<span className="rd-input-suffix"><input className="rd-input" autoFocus maxLength={200} value={name} onChange={(event) => { setName(event.target.value); setError(""); }} /><small>.pdf</small></span></label>
      {error && <p className="rd-error-text" role="alert">{error}</p>}
      <div className="rd-modal-actions"><button type="button" className="rd-button" onClick={onClose}>Huỷ</button><button type="submit" className="rd-button primary" disabled={saving}>{saving ? "Đang lưu…" : "Lưu tên"}</button></div>
    </form>
  </div>;
}

/** An in-app confirm: says what will happen and cannot be dismissed by accident. */
export function ConfirmDialog({ dialog, onClose }) {
  const [working, setWorking] = useState(false);
  const confirmRef = useRef(null);
  useEffect(() => { if (dialog) confirmRef.current?.focus(); }, [dialog]);
  useEffect(() => {
    if (!dialog) return undefined;
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dialog, onClose]);
  if (!dialog) return null;
  const run = async () => { setWorking(true); try { await dialog.onConfirm(); onClose(); } finally { setWorking(false); } };
  return <div className="rd-modal-back" onMouseDown={(event) => { if (event.target === event.currentTarget && !working) onClose(); }}>
    <section className="rd-modal" role="alertdialog" aria-modal="true" aria-labelledby="rd-confirm-title" aria-describedby="rd-confirm-text">
      <h2 id="rd-confirm-title">{dialog.title}</h2>
      <p id="rd-confirm-text" className="rd-small">{dialog.text}</p>
      <div className="rd-modal-actions"><button type="button" className="rd-button" onClick={onClose} disabled={working}>Huỷ</button><button ref={confirmRef} type="button" className={`rd-button ${dialog.danger ? "danger" : "primary"}`} onClick={run} disabled={working}>{working ? "Đang làm…" : dialog.confirmLabel}</button></div>
    </section>
  </div>;
}
