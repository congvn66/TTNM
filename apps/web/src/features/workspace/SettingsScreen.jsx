import { useEffect, useMemo, useState } from "react";
import { request } from "../../shared/api/client.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

const NAV = [
  { id: "profile", label: "Hồ sơ" },
  { id: "preferences", label: "Tùy chọn" },
  { id: "security", label: "Bảo mật" },
];

// "Chrome · macOS" from a browser user agent. Edge and Opera also say Chrome, and Chrome also says Safari, so order matters.
const BROWSERS = [[/Edg\//, "Edge"], [/OPR\//, "Opera"], [/Chrome\//, "Chrome"], [/Firefox\//, "Firefox"], [/Safari\//, "Safari"]];
const SYSTEMS = [[/iPhone|iPad/, "iOS"], [/Android/, "Android"], [/Mac OS X/, "macOS"], [/Windows/, "Windows"], [/Linux/, "Linux"]];
export function describeDevice(userAgent = "") {
  const browser = BROWSERS.find(([pattern]) => pattern.test(userAgent))?.[1];
  const system = SYSTEMS.find(([pattern]) => pattern.test(userAgent))?.[1];
  const parts = [browser, system].filter(Boolean);
  return parts.length ? parts.join(" · ") : userAgent;
}

function Icon({ name, size = 17 }) {
  const paths = {
    arrowLeft: <><path d="m15 18-6-6 6-6" /><path d="M9 12h10" /></>,
    user: <><circle cx="12" cy="8" r="3.2" /><path d="M5 20c.6-3.4 3-5.2 7-5.2s6.4 1.8 7 5.2" /></>,
    settings: <><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" /><circle cx="12" cy="12" r="3.5" /></>,
    lock: <><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" /></>,
    moon: <path d="M20.5 15.2A8.5 8.5 0 0 1 8.8 3.5 8.5 8.5 0 1 0 20.5 15.2Z" />,
    system: <><rect x="4" y="5" width="16" height="11" rx="2" /><path d="M8 20h8M12 16v4" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    logout: <><path d="M10 5H5v14h5" /><path d="m14 8 4 4-4 4M8 12h10" /></>,
  };
  return <svg className="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function initials(user) { return (user?.display_name || user?.email || "S").trim().slice(0, 1).toUpperCase(); }
function FieldError({ children }) { return children ? <span className="settings-field-error" role="alert">{children}</span> : null; }

function ConfirmDialog({ dialog, busy, onClose, onConfirm }) {
  if (!dialog) return null;
  return <div className="resource-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="resource-modal" role="dialog" aria-modal="true" aria-labelledby="settings-confirm-title">
      <div className="resource-modal-icon danger"><span aria-hidden="true">!</span></div>
      <div><h2 id="settings-confirm-title">{dialog.title}</h2></div>
      <div className="resource-modal-actions"><button type="button" className="dialog-secondary" onClick={onClose} disabled={busy}>Hủy</button><button type="button" className="dialog-danger" onClick={onConfirm} disabled={busy}>{busy ? "Đang xử lý…" : dialog.confirmLabel}</button></div>
    </section>
  </div>;
}

function SettingsHeader({ section, user, onNavigate, onSignOut }) {
  const current = NAV.find((item) => item.id === section) ?? NAV[0];
  return <header className="settings-topbar">
    <button className="settings-back" type="button" onClick={() => onNavigate("/app/workspace")}><Icon name="arrowLeft" size={16} /> <span>Về báo cáo</span></button>
    <div className="settings-breadcrumb"><span>Cài đặt</span><b>/</b><strong>{current.label}</strong></div>
    <div className="settings-user"><span className="profile-avatar">{initials(user)}</span><span>{user?.display_name || user?.email || ""}</span>{onSignOut && <button type="button" aria-label="Đăng xuất" onClick={onSignOut}><Icon name="logout" size={15} /></button>}</div>
  </header>;
}

function SettingsNav({ section, onNavigate }) {
  return <nav className="settings-nav" aria-label="Cài đặt tài khoản">
    <div className="settings-nav-heading"><strong>Cài đặt</strong></div>
    {NAV.map((item) => <button key={item.id} type="button" className={section === item.id ? "active" : ""} aria-current={section === item.id ? "page" : undefined} onClick={() => onNavigate(`/app/settings/${item.id}`)}><span className="settings-nav-icon"><Icon name={item.id === "profile" ? "user" : item.id === "preferences" ? "settings" : "lock"} size={16} /></span><span><b>{item.label}</b></span></button>)}
  </nav>;
}

function ProfileSettings({ user, onProfileChange }) {
  const [name, setName] = useState(user?.display_name ?? "");
  const [serverName, setServerName] = useState(user?.display_name ?? "");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("idle");
  useEffect(() => { const value = user?.display_name ?? ""; setName(value); setServerName(value); }, [user?.display_name]);
  const dirty = name !== serverName;
  async function save(event) {
    event.preventDefault();
    const value = name.trim();
    if (value.length < 2 || value.length > 80) { setError("Tên cần từ 2 đến 80 ký tự."); return; }
    setStatus("saving"); setError("");
    try {
      const body = await request("/api/v1/settings/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: value }) });
      const next = body.user?.display_name ?? value;
      setName(next); setServerName(next); setStatus("success"); onProfileChange?.(body.user);
      window.setTimeout(() => setStatus("idle"), 2400);
    } catch (reason) { setError(reason.message); setStatus("error"); }
  }
  return <>
    <div className="settings-heading"><div><h1>Hồ sơ</h1></div></div>
    <form className="settings-card settings-form" onSubmit={save}>
      <div className="settings-fields">
        <label>Tên<input value={name} maxLength={80} onChange={(event) => { setName(event.target.value); setError(""); setStatus("idle"); }} placeholder="Nguyễn Văn A" aria-invalid={Boolean(error)} />{error && <FieldError>{error}</FieldError>}</label>
        <label>Email<input value={user?.email || ""} disabled readOnly /></label>
      </div>
      {status === "success" && <div className="settings-success" role="status"><Icon name="check" size={15} /> Đã lưu.</div>}
      <div className="settings-actions"><button type="button" className="settings-secondary" disabled={!dirty || status === "saving"} onClick={() => { setName(serverName); setError(""); }}>Hủy</button><button className="settings-primary" type="submit" disabled={!dirty || status === "saving"}>{status === "saving" ? "Đang lưu…" : "Lưu"}</button></div>
    </form>
  </>;
}

// Same labels and storage as the reader's theme menu: the choice applies and is kept at once.
const THEMES = [{ value: "system", label: "Tự động", icon: "system" }, { value: "light", label: "Sáng", icon: "sun" }, { value: "dark", label: "Tối", icon: "moon" }];

function PreferencesSettings() {
  const { preference, setPreference } = useTheme();
  return <>
    <div className="settings-heading"><div><h1>Tùy chọn</h1></div></div>
    <section className="settings-card settings-form">
      <div className="settings-card-header"><div><h2>Giao diện</h2></div></div>
      <div className="theme-grid">{THEMES.map((theme) => <button type="button" key={theme.value} className={`theme-option ${preference === theme.value ? "selected" : ""}`} aria-pressed={preference === theme.value} onClick={() => setPreference(theme.value)}><span className="theme-option-icon"><Icon name={theme.icon} size={16} /></span><span><b>{theme.label}</b></span>{preference === theme.value && <span className="theme-check"><Icon name="check" size={13} /></span>}</button>)}</div>
    </section>
  </>;
}

function SecuritySettings() {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState("");
  const [confirm, setConfirm] = useState(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  async function loadSessions() {
    setSessionsError("");
    try { const body = await request("/api/v1/auth/sessions"); setSessions(body.sessions ?? []); }
    catch (reason) { setSessionsError(reason.message); }
    finally { setSessionsLoading(false); }
  }

  useEffect(() => { loadSessions(); }, []);

  async function revokeSession(session) {
    setConfirm({ title: "Đăng xuất thiết bị này?", confirmLabel: "Đăng xuất", action: async () => { try { const result = await request(`/api/v1/auth/sessions/${session.id}`, { method: "DELETE" }); if (result.current) window.location.reload(); else await loadSessions(); } catch (reason) { setSessionsError(reason.message); } } });
  }

  async function revokeOthers() {
    setConfirm({ title: "Đăng xuất các thiết bị khác?", confirmLabel: "Đăng xuất", action: async () => { try { await request("/api/v1/auth/sessions/revoke-others", { method: "POST" }); await loadSessions(); } catch (reason) { setSessionsError(reason.message); } } });
  }

  async function confirmAction() { if (!confirm?.action) return; setConfirmBusy(true); try { await confirm.action(); setConfirm(null); } finally { setConfirmBusy(false); } }

  async function save(event) {
    event.preventDefault();
    setError("");
    if (!form.current_password) { setError("Nhập mật khẩu hiện tại."); return; }
    if (form.new_password.length < 8) { setError("Mật khẩu mới cần ít nhất 8 ký tự."); return; }
    if (form.new_password !== form.confirm_password) { setError("Mật khẩu nhập lại không khớp."); return; }
    setStatus("saving");
    try {
      await request("/api/v1/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: form.current_password, new_password: form.new_password }),
      });
      setForm({ current_password: "", new_password: "", confirm_password: "" });
      setStatus("success");
      window.setTimeout(() => setStatus("idle"), 2800);
    } catch (reason) {
      setError(reason.message);
      setStatus("error");
    }
  }

  return <>
    <div className="settings-heading"><div><h1>Bảo mật</h1></div></div>
    <form className="settings-card settings-form security-card" onSubmit={save} noValidate>
      <div className="settings-card-header"><div><h2>Đổi mật khẩu</h2><p>Các thiết bị khác sẽ bị đăng xuất.</p></div><span className="settings-info-icon"><Icon name="lock" size={17} /></span></div>
      <div className="settings-fields">
        <label>Mật khẩu hiện tại<input type="password" autoComplete="current-password" value={form.current_password} onChange={(event) => setForm({ ...form, current_password: event.target.value })} aria-required="true" /></label>
        <label>Mật khẩu mới<input type="password" autoComplete="new-password" value={form.new_password} onChange={(event) => setForm({ ...form, new_password: event.target.value })} aria-required="true" /><small className="settings-help">Tối thiểu 8 ký tự.</small></label>
        <label>Nhập lại mật khẩu mới<input type="password" autoComplete="new-password" value={form.confirm_password} onChange={(event) => setForm({ ...form, confirm_password: event.target.value })} aria-required="true" /></label>
      </div>
      {error && <div className="settings-error" role="alert">{error}</div>}
      {status === "success" && <div className="settings-success" role="status"><Icon name="check" size={15} /> Đã đổi mật khẩu.</div>}
      <div className="settings-actions"><button className="settings-primary" type="submit" disabled={status === "saving"}>{status === "saving" ? "Đang lưu…" : "Đổi mật khẩu"}</button></div>
    </form>
    <section className="settings-card security-card"><div className="settings-card-header"><div><h2>Thiết bị</h2></div><button type="button" className="settings-secondary" onClick={revokeOthers}>Đăng xuất thiết bị khác</button></div>{sessionsError && <div className="settings-error" role="alert">{sessionsError}</div>}{sessionsLoading ? <div className="settings-skeleton-group"><i></i></div> : <div className="device-list">{sessions.length ? sessions.map((session) => <article className="device-row" key={session.id}><span className={`device-dot ${session.current ? "current" : ""}`}></span><div><strong>{describeDevice(session.user_agent)}</strong><small>{[session.current && "Thiết bị này", session.last_seen_at && `Hoạt động ${new Date(session.last_seen_at).toLocaleString("vi-VN")}`].filter(Boolean).join(" · ")}</small></div><button type="button" className="device-revoke" onClick={() => revokeSession(session)}>Đăng xuất</button></article>) : <p className="settings-help">Không có thiết bị nào.</p>}</div>}</section>
    <ConfirmDialog dialog={confirm} busy={confirmBusy} onClose={() => setConfirm(null)} onConfirm={confirmAction} />
  </>;
}

export default function SettingsScreen({ section = "profile", user = null, onSignOut = null, onNavigate }) {
  const safeSection = NAV.some((item) => item.id === section) ? section : "profile";
  const [profile, setProfile] = useState(user);
  useEffect(() => setProfile(user), [user]);
  const content = useMemo(() => safeSection === "profile" ? <ProfileSettings user={profile} onProfileChange={setProfile} /> : safeSection === "preferences" ? <PreferencesSettings /> : <SecuritySettings />, [profile, safeSection]);
  return <div className="settings-shell">
    <a className="skip-link" href="#settings-content">Bỏ qua điều hướng</a>
    <SettingsHeader section={safeSection} user={profile} onNavigate={onNavigate} onSignOut={onSignOut} />
    <div className="settings-layout"><SettingsNav section={safeSection} onNavigate={onNavigate} /><main className="settings-content" id="settings-content">{content}</main></div>
  </div>;
}
