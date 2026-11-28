import { useEffect, useState } from "react";
import { request } from "../../shared/api/client.js";
import { useTheme } from "../theme/ThemeProvider.jsx";
import { Icon } from "../reader/Icon.jsx";
import { useReports } from "../reader/useReports.js";
import { describeDevice, formatSeen, groupSessions } from "./devices.js";
import { ActionDialog } from "./Dialog.jsx";
import { WorkspaceShell } from "./WorkspaceShell.jsx";

export { describeDevice };

const NAV = [
  { id: "profile", label: "Hồ sơ" },
  { id: "preferences", label: "Tùy chọn" },
  { id: "security", label: "Bảo mật" },
];
const JSON_HEADERS = { "Content-Type": "application/json" };
// Rows shown before "Xem thêm".
const DEVICE_ROWS = 5;

function Tabs({ section, onNavigate }) {
  return <nav className="ws-tabs" aria-label="Cài đặt tài khoản">
    {NAV.map((item) => <button key={item.id} type="button" className={section === item.id ? "active" : ""} aria-current={section === item.id ? "page" : undefined} onClick={() => onNavigate(`/app/settings/${item.id}`)}>{item.label}</button>)}
  </nav>;
}

function Notice({ kind, children }) {
  return children ? <p className={`ws-form-note ${kind}`} role={kind === "error" ? "alert" : "status"}>{kind === "success" && <span aria-hidden="true">✓</span>}{children}</p> : null;
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
      const body = await request("/api/v1/settings/profile", { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ display_name: value }) });
      const next = body.user?.display_name ?? value;
      setName(next); setServerName(next); setStatus("success");
      onProfileChange?.(body.user ?? { ...user, display_name: next });
      window.setTimeout(() => setStatus((current) => (current === "success" ? "idle" : current)), 2400);
    } catch (reason) { setError(reason.message); setStatus("error"); }
  }
  return <form className="ws-panel" onSubmit={save} noValidate>
    <h2>Hồ sơ</h2>
    <div className="ws-fields">
      <label className="rd-field">Tên<input className="ws-input" value={name} maxLength={80} autoComplete="name" onChange={(event) => { setName(event.target.value); setError(""); setStatus("idle"); }} placeholder="Nguyễn Văn A" aria-invalid={Boolean(error)} /></label>
      <label className="rd-field">Email<input className="ws-input" value={user?.email || ""} disabled readOnly /></label>
    </div>
    <Notice kind="error">{error}</Notice>
    <Notice kind="success">{status === "success" ? "Đã lưu." : ""}</Notice>
    <div className="ws-panel-actions"><button type="button" className="rd-button" disabled={!dirty || status === "saving"} onClick={() => { setName(serverName); setError(""); }}>Hủy</button><button className="rd-button primary" type="submit" disabled={!dirty || status === "saving"}>{status === "saving" ? "Đang lưu…" : "Lưu"}</button></div>
  </form>;
}

// Same labels, icons and storage as the theme buttons in the sidebar: the choice applies and is kept at once.
const THEMES = [{ value: "system", label: "Tự động", icon: "monitor" }, { value: "light", label: "Sáng", icon: "sun" }, { value: "dark", label: "Tối", icon: "moon" }];

function PreferencesSettings() {
  const { preference, setPreference } = useTheme();
  return <section className="ws-panel">
    <h2>Giao diện</h2>
    <div className="ws-theme-grid">{THEMES.map((theme) => <button type="button" key={theme.value} className={`ws-theme${preference === theme.value ? " selected" : ""}`} aria-pressed={preference === theme.value} onClick={() => setPreference(theme.value)}><Icon name={theme.icon} size={18} /><span>{theme.label}</span></button>)}</div>
  </section>;
}

async function revokeAll(ids) {
  // A few at a time: one device can hold many sign-ins.
  for (let index = 0; index < ids.length; index += 4) {
    await Promise.all(ids.slice(index, index + 4).map((id) => request(`/api/v1/auth/sessions/${id}`, { method: "DELETE" })));
  }
}

function SecuritySettings({ onSignOut }) {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [sessions, setSessions] = useState(null);
  const [sessionsError, setSessionsError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [dialog, setDialog] = useState(null);

  async function loadSessions() {
    setSessionsError("");
    try { const body = await request("/api/v1/auth/sessions"); setSessions(body.sessions ?? []); }
    catch (reason) { setSessionsError(reason.message); setSessions((current) => current ?? []); }
  }
  useEffect(() => { loadSessions(); }, []);

  const groups = groupSessions(sessions ?? []);
  const others = groups.filter((group) => !group.current);
  const shownGroups = showAll ? groups : groups.slice(0, DEVICE_ROWS);

  function signOutGroup(group) {
    if (group.current) {
      setDialog({ title: "Đăng xuất thiết bị này?", confirmLabel: "Đăng xuất", busyLabel: "Đang đăng xuất…", danger: true, onConfirm: async () => { await onSignOut?.(); } });
      return;
    }
    const count = group.sessions.length;
    setDialog({ title: count > 1 ? `Đăng xuất ${count} lần đăng nhập trên ${group.name}?` : `Đăng xuất ${group.name}?`, confirmLabel: "Đăng xuất", busyLabel: "Đang đăng xuất…", danger: true, onConfirm: async () => {
      await revokeAll(group.sessions.map((session) => session.id));
      await loadSessions();
    } });
  }
  const signOutOthers = () => setDialog({ title: "Đăng xuất các thiết bị khác?", confirmLabel: "Đăng xuất", busyLabel: "Đang đăng xuất…", danger: true, onConfirm: async () => {
    await request("/api/v1/auth/sessions/revoke-others", { method: "POST" });
    await loadSessions();
  } });

  async function save(event) {
    event.preventDefault();
    setError("");
    if (!form.current_password) { setError("Nhập mật khẩu hiện tại."); return; }
    if (form.new_password.length < 8) { setError("Mật khẩu mới cần ít nhất 8 ký tự."); return; }
    if (form.new_password !== form.confirm_password) { setError("Mật khẩu nhập lại không khớp."); return; }
    setStatus("saving");
    try {
      await request("/api/v1/auth/change-password", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ current_password: form.current_password, new_password: form.new_password }) });
      setForm({ current_password: "", new_password: "", confirm_password: "" });
      setStatus("success");
      loadSessions();
      window.setTimeout(() => setStatus((current) => (current === "success" ? "idle" : current)), 2800);
    } catch (reason) { setError(reason.message); setStatus("error"); }
  }
  const field = (name) => ({ className: "ws-input", type: "password", value: form[name], "aria-required": "true", onChange: (event) => { setForm({ ...form, [name]: event.target.value }); setError(""); } });

  return <>
    <form className="ws-panel security-card" onSubmit={save} noValidate>
      <h2>Đổi mật khẩu</h2>
      <p className="ws-panel-note">Các thiết bị khác sẽ bị đăng xuất.</p>
      <div className="ws-fields single">
        <label className="rd-field">Mật khẩu hiện tại<input {...field("current_password")} autoComplete="current-password" /></label>
        <label className="rd-field">Mật khẩu mới<input {...field("new_password")} autoComplete="new-password" placeholder="Tối thiểu 8 ký tự" /></label>
        <label className="rd-field">Nhập lại mật khẩu mới<input {...field("confirm_password")} autoComplete="new-password" /></label>
      </div>
      <Notice kind="error">{error}</Notice>
      <Notice kind="success">{status === "success" ? "Đã đổi mật khẩu." : ""}</Notice>
      <div className="ws-panel-actions"><button className="rd-button primary" type="submit" disabled={status === "saving"}>{status === "saving" ? "Đang lưu…" : "Đổi mật khẩu"}</button></div>
    </form>
    <section className="ws-panel">
      <div className="ws-panel-head"><h2>Thiết bị</h2>{others.length > 0 && <button type="button" className="rd-button" onClick={signOutOthers}>Đăng xuất thiết bị khác</button>}</div>
      {sessionsError && <div className="ws-notice" role="alert"><span>{sessionsError}</span><button type="button" className="rd-button" onClick={loadSessions}>Thử lại</button></div>}
      {sessions === null ? <div className="ws-state compact" role="status"><span className="rd-spinner" aria-hidden="true" />Đang tải…</div>
        : !groups.length ? <p className="ws-panel-note">Không có thiết bị nào.</p>
        : <ul className="ws-devices">
          {shownGroups.map((group) => <li key={group.key}>
            <span className={`ws-device-dot${group.current ? " current" : ""}`} aria-hidden="true" />
            <div><b>{group.name}</b><small>{[group.current ? "Thiết bị này" : group.sessions.length > 1 ? `${group.sessions.length} lần đăng nhập` : "", group.lastSeen && `Hoạt động ${formatSeen(group.lastSeen)}`].filter(Boolean).join(" · ")}</small></div>
            <button type="button" className="rd-button ws-small-button" onClick={() => signOutGroup(group)}>Đăng xuất</button>
          </li>)}
        </ul>}
      {groups.length > DEVICE_ROWS && <button type="button" className="rd-link ws-more" onClick={() => setShowAll(!showAll)}>{showAll ? "Thu gọn" : `Xem thêm ${groups.length - DEVICE_ROWS} thiết bị`}</button>}
    </section>
    <ActionDialog dialog={dialog} onClose={() => setDialog(null)} />
  </>;
}

/** Account pages in the reader's frame: profile, appearance, password and devices. */
export default function SettingsScreen({ section = "profile", user = null, onSignOut = null, onNavigate, onUserChange = null }) {
  const safeSection = NAV.some((item) => item.id === section) ? section : "profile";
  const reports = useReports({ user, syncUrl: false });
  return <WorkspaceShell page="settings" title="Cài đặt" reports={reports} user={user} onNavigate={onNavigate} onSignOut={onSignOut}>
    <div className="ws-page ws-settings">
      <Tabs section={safeSection} onNavigate={onNavigate} />
      {safeSection === "profile" ? <ProfileSettings user={user} onProfileChange={onUserChange} /> : safeSection === "preferences" ? <PreferencesSettings /> : <SecuritySettings onSignOut={onSignOut} />}
    </div>
  </WorkspaceShell>;
}
