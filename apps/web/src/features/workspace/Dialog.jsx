import { useEffect, useRef, useState } from "react";

const FOCUSABLE = "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";

/**
 * A dialog for one action: a name to type, or a yes/no question.
 * It stays open while the request runs and shows its error in place, so a failed
 * create keeps the typed name and "Thử lại" sends it again. Escape and the backdrop
 * close it, except while busy. Tab stays inside, and focus goes back where it was.
 *
 * dialog = { title, text?, value? (asks for a name), confirmLabel, busyLabel?, danger?, onConfirm(value) }
 */
export function ActionDialog({ dialog, onClose }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const panelRef = useRef(null);
  const naming = dialog && dialog.value !== undefined;

  useEffect(() => {
    if (!dialog) return undefined;
    setValue(dialog.value ?? ""); setBusy(false); setError("");
    const opener = document.activeElement;
    window.requestAnimationFrame(() => {
      const panel = panelRef.current;
      const first = panel?.querySelector("input") ?? panel?.querySelector(".rd-modal-actions button:last-child");
      first?.focus(); if (first?.select) first.select();
    });
    return () => { if (opener?.isConnected) opener.focus?.({ preventScroll: true }); };
  }, [dialog]);

  if (!dialog) return null;
  const close = () => { if (!busy) onClose(); };
  const submit = async (event) => {
    event?.preventDefault();
    const text = value.trim();
    if (naming && !text) { setError("Nhập tên."); return; }
    setBusy(true); setError("");
    try { await dialog.onConfirm(text); setBusy(false); onClose(); }
    catch (failure) { setBusy(false); setError(failure?.message || "Đã xảy ra lỗi. Thử lại."); }
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") { event.stopPropagation(); close(); return; }
    if (event.key !== "Tab") return;
    const items = [...panelRef.current.querySelectorAll(FOCUSABLE)];
    if (!items.length) return;
    const first = items[0]; const last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  const confirmClass = `rd-button ${dialog.danger ? "danger" : "primary"}`;
  return <div className="rd-modal-back" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <form ref={panelRef} className="rd-modal ws-dialog" role={dialog.danger ? "alertdialog" : "dialog"} aria-modal="true" aria-labelledby="ws-dialog-title" aria-describedby={dialog.text ? "ws-dialog-text" : undefined} aria-busy={busy} onSubmit={submit} onKeyDown={onKeyDown} noValidate>
      <h2 id="ws-dialog-title">{dialog.title}</h2>
      {dialog.text && <p id="ws-dialog-text" className="rd-small">{dialog.text}</p>}
      {naming && <label className="rd-field">Tên<input className="ws-input" value={value} maxLength={120} disabled={busy} aria-invalid={Boolean(error)} onChange={(event) => { setValue(event.target.value); setError(""); }} /></label>}
      {error && <p className="rd-error-text" role="alert">{error}</p>}
      <div className="rd-modal-actions">
        <button type="button" className="rd-button" onClick={close} disabled={busy}>{dialog.onConfirm ? "Hủy" : "Đóng"}</button>
        {dialog.onConfirm && <button type="submit" className={confirmClass} disabled={busy}>{busy ? <><span className="rd-spinner small" aria-hidden="true" />{dialog.busyLabel ?? "Đang lưu…"}</> : error ? "Thử lại" : dialog.confirmLabel}</button>}
      </div>
    </form>
  </div>;
}
