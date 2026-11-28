import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon.jsx";
import { reportMeta, StatusDot } from "./Home.jsx";

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

function Menu({ items }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef(null);
  const panelRef = useRef(null);
  useDismiss(open, () => setOpen(false), [buttonRef, panelRef]);
  return <div className="rd-menu">
    <button ref={buttonRef} type="button" className="rd-icon-button" aria-label="Tùy chọn báo cáo" title="Tùy chọn báo cáo" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((value) => !value)}>
      <Icon name="more" />
    </button>
    {open && <div ref={panelRef} className="rd-popover rd-menu-panel" role="menu">
      {items.filter(Boolean).map((item) => <button key={item.label} type="button" role="menuitem" disabled={item.disabled} className={item.danger ? "danger" : ""} onClick={() => { setOpen(false); item.onClick(); }}>{item.label}</button>)}
    </div>}
  </div>;
}

const THEMES = [{ value: "system", icon: "monitor", label: "Tự động" }, { value: "light", icon: "sun", label: "Sáng" }, { value: "dark", icon: "moon", label: "Tối" }];

function AccountMenu({ user, onSettings, onSignOut }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef(null);
  const panelRef = useRef(null);
  useDismiss(open, () => setOpen(false), [buttonRef, panelRef]);
  const name = user.display_name || user.email || "";
  return <div className="rd-account">
    <button ref={buttonRef} type="button" className="rd-side-item" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <span className="rd-avatar" aria-hidden="true">{name.trim().charAt(0).toUpperCase() || "?"}</span><span className="rd-side-label">{name}</span>
    </button>
    {open && <div ref={panelRef} className="rd-popover rd-menu-panel rd-account-panel" role="menu">
      <button type="button" role="menuitem" onClick={() => { setOpen(false); onSettings(); }}><Icon name="settings" size={16} /><span>Cài đặt</span></button>
      <hr />
      <button type="button" role="menuitem" onClick={() => { setOpen(false); onSignOut(); }}><Icon name="logout" size={16} /><span>Đăng xuất</span></button>
    </div>}
  </div>;
}

/** Reports down the left, like a file list; app settings and the account at the bottom. */
export function Sidebar({ open, onClose, reports, selected, onOpen, onHome, onNew, onLibrary, user, onSettings, onSignOut, theme, onTheme, sound, onSound }) {
  const [query, setQuery] = useState("");
  const shown = reports.filter((report) => report.file_name.toLowerCase().includes(query.trim().toLowerCase()));
  return <>
    {open && <div className="rd-side-back" onClick={onClose} aria-hidden="true" />}
    <nav className={`rd-side${open ? " open" : ""}`} aria-label="Báo cáo">
      <div className="rd-side-head">
        <button type="button" className="rd-brand" onClick={onHome}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M16 16l5 5" /><path d="M8 11h6" /></svg>
          <span>SourceLens</span>
        </button>
        <button type="button" className="rd-icon-button" aria-label="Ẩn thanh bên" title="Ẩn thanh bên" onClick={onClose}><Icon name="sidebar" /></button>
      </div>
      <button type="button" className="rd-button primary rd-side-upload" onClick={onNew}><Icon name="upload" size={16} />Tải lên</button>
      {reports.length > 5 && <label className="rd-side-search"><Icon name="search" size={15} /><input placeholder="Tìm báo cáo" aria-label="Tìm báo cáo" value={query} onChange={(event) => setQuery(event.target.value)} /></label>}
      <div className="rd-side-list">
        {reports.length > 0 && <p className="rd-side-heading">Báo cáo</p>}
        <ul>{shown.map((report) => <li key={report.id}>
          <button type="button" className={`rd-side-item${report.id === selected?.id ? " active" : ""}`} aria-current={report.id === selected?.id ? "page" : undefined} onClick={() => onOpen(report.id)} title={report.file_name}>
            <StatusDot report={report} /><span className="rd-side-label">{report.file_name.replace(/\.pdf$/i, "")}</span>
          </button>
        </li>)}</ul>
        {reports.length > 0 && !shown.length && <p className="rd-side-empty">Không có kết quả</p>}
      </div>
      <div className="rd-side-foot">
        {onLibrary && <button type="button" className="rd-side-item" onClick={onLibrary}><Icon name="folder" size={16} /><span className="rd-side-label">Thư viện</span></button>}
        <div className="rd-side-controls">
          <div className="rd-icon-segment" role="radiogroup" aria-label="Giao diện">
            {THEMES.map((item) => <button key={item.value} type="button" role="radio" aria-checked={theme === item.value} aria-label={item.label} title={item.label} className={theme === item.value ? "active" : ""} onClick={() => onTheme(item.value)}><Icon name={item.icon} size={16} /></button>)}
          </div>
          <button type="button" className={`rd-icon-button${sound ? " on" : ""}`} aria-pressed={sound} aria-label="Âm báo khi đọc xong" title={sound ? "Âm báo: bật" : "Âm báo: tắt"} onClick={onSound}><Icon name={sound ? "bell" : "bellOff"} size={16} /></button>
        </div>
        {user && <AccountMenu user={user} onSettings={onSettings} onSignOut={onSignOut} />}
      </div>
    </nav>
  </>;
}

export function TopBar({ selected, sidebarOpen, onToggleSidebar, onHelp, menuItems }) {
  const meta = selected ? reportMeta(selected, { withDate: false }) : "";
  return <header className="rd-top">
    {!sidebarOpen && <button type="button" className="rd-icon-button" aria-label="Hiện thanh bên" title="Hiện thanh bên" onClick={onToggleSidebar}><Icon name="sidebar" /></button>}
    {selected && <div className="rd-top-title"><StatusDot report={selected} /><span><b>{selected.file_name}</b>{meta && <small>{meta}</small>}</span></div>}
    <div className="rd-top-actions">
      <button type="button" className="rd-icon-button" aria-label="Phím tắt" title="Phím tắt" onClick={onHelp}><Icon name="help" /></button>
      {selected && <Menu items={menuItems} />}
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
  return <div className="rd-drop-overlay" aria-hidden="true"><div><b>Thả để tải lên</b></div></div>;
}

export function HelpDialog({ open, onClose }) {
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
      <h2 id="rd-help-title">Phím tắt</h2>
      <dl className="rd-keys"><div><dt><kbd>/</kbd></dt><dd>Đặt câu hỏi</dd></div><div><dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Trang trước, trang sau</dd></div><div><dt><kbd>Esc</kbd></dt><dd>Tắt đánh dấu trên trang</dd></div><div><dt><kbd>?</kbd></dt><dd>Xem phím tắt</dd></div></dl>
      <div className="rd-modal-actions"><button ref={closeRef} type="button" className="rd-button primary" onClick={onClose}>Đóng</button></div>
    </section>
  </div>;
}

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
    if (!name.trim()) { setError("Nhập tên"); return; }
    setSaving(true); setError("");
    try { await onSave(report, `${name.trim()}.pdf`); onClose(); } catch (failure) { setError(failure.message); } finally { setSaving(false); }
  };
  return <div className="rd-modal-back" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="rd-modal" role="dialog" aria-modal="true" aria-labelledby="rd-rename-title" onSubmit={submit}>
      <h2 id="rd-rename-title">Đổi tên báo cáo</h2>
      <label className="rd-field">Tên<span className="rd-input-suffix"><input className="rd-input" autoFocus maxLength={200} value={name} onChange={(event) => { setName(event.target.value); setError(""); }} /><small>.pdf</small></span></label>
      {error && <p className="rd-error-text" role="alert">{error}</p>}
      <div className="rd-modal-actions"><button type="button" className="rd-button" onClick={onClose}>Hủy</button><button type="submit" className="rd-button primary" disabled={saving}>{saving ? "Đang lưu…" : "Lưu"}</button></div>
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
      <div className="rd-modal-actions"><button type="button" className="rd-button" onClick={onClose} disabled={working}>Hủy</button><button ref={confirmRef} type="button" className={`rd-button ${dialog.danger ? "danger" : "primary"}`} onClick={run} disabled={working}>{working ? dialog.busyLabel ?? "Đang xử lý…" : dialog.confirmLabel}</button></div>
    </section>
  </div>;
}
