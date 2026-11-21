import { useEffect, useMemo, useState } from "react";
import { request } from "../../shared/api/client.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

const NAV = [
  { id: "profile", label: "Hồ sơ", description: "Tên hiển thị và tài khoản" },
  { id: "preferences", label: "Tuỳ chọn", description: "Giao diện và trình đọc" },
  { id: "security", label: "Bảo mật", description: "Mật khẩu và phiên đăng nhập" },
];

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

function SettingsHeader({ section, user, onNavigate, onSignOut }) {
  const current = NAV.find((item) => item.id === section) ?? NAV[0];
  return <header className="settings-topbar">
    <button className="settings-back" type="button" onClick={() => onNavigate("/app/workspace")}><Icon name="arrowLeft" size={16} /> <span>Workspace</span></button>
    <div className="settings-breadcrumb"><span>Cài đặt</span><b>/</b><strong>{current.label}</strong></div>
    <div className="settings-user"><span className="profile-avatar">{initials(user)}</span><span>{user?.display_name || "Workspace cá nhân"}</span>{onSignOut && <button type="button" aria-label="Đăng xuất" onClick={onSignOut}><Icon name="logout" size={15} /></button>}</div>
  </header>;
}

function SettingsNav({ section, onNavigate }) {
  return <nav className="settings-nav" aria-label="Cài đặt tài khoản">
    <div className="settings-nav-heading"><span>ACCOUNT</span><strong>Cài đặt</strong></div>
    {NAV.map((item) => <button key={item.id} type="button" className={section === item.id ? "active" : ""} aria-current={section === item.id ? "page" : undefined} onClick={() => onNavigate(`/app/settings/${item.id}`)}><span className="settings-nav-icon"><Icon name={item.id === "profile" ? "user" : item.id === "preferences" ? "settings" : "lock"} size={16} /></span><span><b>{item.label}</b><small>{item.description}</small></span></button>)}
    <div className="settings-nav-foot"><span className="settings-secure-dot"></span><span>Dữ liệu của bạn được lưu theo tài khoản và phiên.</span></div>
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
    if (value.length < 2 || value.length > 80) { setError("Tên hiển thị cần từ 2 đến 80 ký tự."); return; }
    setStatus("saving"); setError("");
    try {
      const body = await request("/api/v1/settings/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: value }) });
      const next = body.user?.display_name ?? value;
      setName(next); setServerName(next); setStatus("success"); onProfileChange?.(body.user);
      window.setTimeout(() => setStatus("idle"), 2400);
    } catch (reason) { setError(reason.message || "Không thể lưu hồ sơ."); setStatus("error"); }
  }
  return <>
    <div className="settings-heading"><div><span className="settings-eyebrow">PROFILE</span><h1>Hồ sơ</h1><p>Thông tin được hiển thị trong workspace và các phiên phân tích của bạn.</p></div><span className="settings-status-dot"><i></i> Tài khoản đang hoạt động</span></div>
    <form className="settings-card settings-form" onSubmit={save}>
      <div className="settings-card-header"><div><h2>Thông tin tài khoản</h2><p>Email đăng nhập là định danh cố định của tài khoản.</p></div><span className="profile-avatar large">{initials(user)}</span></div>
      <div className="settings-fields">
        <label>Tên hiển thị<input value={name} maxLength={80} onChange={(event) => { setName(event.target.value); setError(""); setStatus("idle"); }} placeholder="Nguyễn Văn A" aria-invalid={Boolean(error)} />{error && <FieldError>{error}</FieldError>}</label>
        <label>Email<input value={user?.email || "Chế độ demo · chưa yêu cầu đăng nhập"} disabled readOnly /><small className="settings-help">Email chỉ có thể thay đổi qua quy trình bảo mật riêng.</small></label>
      </div>
      {status === "success" && <div className="settings-success" role="status"><Icon name="check" size={15} /> Đã lưu thay đổi hồ sơ.</div>}
      <div className="settings-actions"><button type="button" className="settings-secondary" disabled={!dirty || status === "saving"} onClick={() => { setName(serverName); setError(""); }}>Huỷ thay đổi</button><button className="settings-primary" type="submit" disabled={!dirty || status === "saving"}>{status === "saving" ? "Đang lưu…" : "Lưu hồ sơ"}</button></div>
    </form>
    <div className="settings-card settings-info-card"><span className="settings-info-icon"><Icon name="user" size={17} /></span><div><h2>Ảnh đại diện</h2><p>Trong bản hiện tại, SourceLens dùng chữ cái đầu để hiển thị nhất quán trên các màn hình. Upload ảnh sẽ bật khi object upload API được phát hành.</p></div><span className="settings-tag">Sắp có</span></div>
  </>;
}

const DEFAULT_PREFS = { theme: "system", locale: "vi-VN", default_answer_style: "grounded" };
function ThemeOption({ value, label, icon, selected, onSelect }) {
  return <button type="button" className={`theme-option ${selected ? "selected" : ""}`} aria-pressed={selected} onClick={() => onSelect(value)}><span className="theme-option-icon"><Icon name={icon} size={16} /></span><span><b>{label}</b><small>{value === "system" ? "Theo thiết bị" : value === "light" ? "Nền sáng rõ ràng" : "Dịu mắt ban đêm"}</small></span>{selected && <span className="theme-check"><Icon name="check" size={13} /></span>}</button>;
}

function PreferencesSettings() {
  const { preference, setPreference } = useTheme();
  const [prefs, setPrefs] = useState({ ...DEFAULT_PREFS, theme: preference });
  const [serverPrefs, setServerPrefs] = useState({ ...DEFAULT_PREFS, theme: preference });
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    request("/api/v1/settings/preferences").then((body) => { if (active) { const next = { ...DEFAULT_PREFS, ...(body.preferences || {}) }; setPrefs(next); setServerPrefs(next); setPreference(next.theme); } }).catch((reason) => { if (active) setError(reason.message || "Không thể tải tuỳ chọn."); }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [setPreference]);
  const dirty = JSON.stringify(prefs) !== JSON.stringify(serverPrefs);
  async function save(event) {
    event.preventDefault(); setStatus("saving"); setError("");
    try { const body = await request("/api/v1/settings/preferences", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(prefs) }); const next = { ...DEFAULT_PREFS, ...(body.preferences || prefs) }; setPrefs(next); setServerPrefs(next); setPreference(next.theme); setStatus("success"); window.setTimeout(() => setStatus("idle"), 2400); }
    catch (reason) { setError(reason.message || "Không thể lưu tuỳ chọn."); setStatus("error"); }
  }
  function update(key, value) { setPrefs((current) => ({ ...current, [key]: value })); if (key === "theme") setPreference(value); setStatus("idle"); }
  return <>
    <div className="settings-heading"><div><span className="settings-eyebrow">PREFERENCES</span><h1>Tuỳ chọn</h1><p>Cá nhân hoá cách SourceLens hiển thị tài liệu và câu trả lời.</p></div></div>
    <form className="settings-card settings-form" onSubmit={save}>
      <div className="settings-card-header"><div><h2>Giao diện</h2><p>Thay đổi được preview ngay; chỉ ghi bền sau khi bạn lưu.</p></div></div>
      {loading ? <div className="settings-skeleton-group"><i></i><i></i><i></i></div> : <>
        <div className="theme-grid"><ThemeOption value="system" label="Hệ thống" icon="system" selected={prefs.theme === "system"} onSelect={(value) => update("theme", value)} /><ThemeOption value="light" label="Sáng" icon="sun" selected={prefs.theme === "light"} onSelect={(value) => update("theme", value)} /><ThemeOption value="dark" label="Tối" icon="moon" selected={prefs.theme === "dark"} onSelect={(value) => update("theme", value)} /></div>
        <div className="settings-divider"></div>
        <div className="settings-row"><div><label htmlFor="settings-locale">Ngôn ngữ</label><small>Ngôn ngữ dùng cho nhãn giao diện và thông báo.</small></div><select id="settings-locale" value={prefs.locale} onChange={(event) => update("locale", event.target.value)}><option value="vi-VN">Tiếng Việt</option><option value="en-US">English</option></select></div>
        <div className="settings-row"><div><label htmlFor="settings-answer-style">Phong cách câu trả lời</label><small>Grounded ưu tiên nguồn dẫn và cảnh báo khi thiếu dữ liệu.</small></div><select id="settings-answer-style" value={prefs.default_answer_style} onChange={(event) => update("default_answer_style", event.target.value)}><option value="grounded">Có căn cứ</option><option value="concise">Ngắn gọn</option></select></div>
      </>}
      {error && <div className="settings-error" role="alert">{error}</div>}
      {status === "success" && <div className="settings-success" role="status"><Icon name="check" size={15} /> Đã lưu tuỳ chọn.</div>}
      <div className="settings-actions"><button type="button" className="settings-secondary" disabled={!dirty || status === "saving"} onClick={() => { setPrefs(serverPrefs); setPreference(serverPrefs.theme); }}>Huỷ thay đổi</button><button className="settings-primary" type="submit" disabled={!dirty || loading || status === "saving"}>{status === "saving" ? "Đang lưu…" : "Lưu tuỳ chọn"}</button></div>
    </form>
  </>;
}

function SecuritySettings() {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState("");

  async function loadSessions() {
    setSessionsError("");
    try { const body = await request("/api/v1/auth/sessions"); setSessions(body.sessions ?? []); }
    catch (reason) { setSessionsError(reason.message || "Không thể tải danh sách thiết bị."); }
    finally { setSessionsLoading(false); }
  }

  useEffect(() => { loadSessions(); }, []);

  async function revokeSession(session) {
    if (!window.confirm(session.current ? "Thu hồi phiên hiện tại và đăng xuất?" : "Thu hồi thiết bị này?")) return;
    try { const result = await request(`/api/v1/auth/sessions/${session.id}`, { method: "DELETE" }); if (result.current) window.location.reload(); else await loadSessions(); }
    catch (reason) { setSessionsError(reason.message || "Không thể thu hồi thiết bị."); }
  }

  async function revokeOthers() {
    if (!window.confirm("Đăng xuất tất cả thiết bị khác?")) return;
    try { await request("/api/v1/auth/sessions/revoke-others", { method: "POST" }); await loadSessions(); }
    catch (reason) { setSessionsError(reason.message || "Không thể thu hồi các thiết bị khác."); }
  }

  async function save(event) {
    event.preventDefault();
    setError("");
    if (form.new_password.length < 8) { setError("Mật khẩu mới cần ít nhất 8 ký tự."); return; }
    if (form.new_password !== form.confirm_password) { setError("Hai mật khẩu mới chưa khớp."); return; }
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
      setError(reason.message || "Không thể đổi mật khẩu lúc này.");
      setStatus("error");
    }
  }

  return <>
    <div className="settings-heading"><div><span className="settings-eyebrow">SECURITY</span><h1>Bảo mật</h1><p>Kiểm soát cách tài khoản được bảo vệ khi làm việc với dữ liệu.</p></div></div>
    <form className="settings-card settings-form security-card" onSubmit={save}>
      <div className="settings-card-header"><div><h2>Đổi mật khẩu</h2><p>Phiên hiện tại vẫn được giữ, các phiên đăng nhập khác sẽ bị thu hồi.</p></div><span className="settings-info-icon"><Icon name="lock" size={17} /></span></div>
      <div className="settings-fields">
        <label>Mật khẩu hiện tại<input type="password" autoComplete="current-password" value={form.current_password} onChange={(event) => setForm({ ...form, current_password: event.target.value })} required /></label>
        <label>Mật khẩu mới<input type="password" autoComplete="new-password" minLength={8} value={form.new_password} onChange={(event) => setForm({ ...form, new_password: event.target.value })} required /><small className="settings-help">Tối thiểu 8 ký tự.</small></label>
        <label>Xác nhận mật khẩu mới<input type="password" autoComplete="new-password" minLength={8} value={form.confirm_password} onChange={(event) => setForm({ ...form, confirm_password: event.target.value })} required /></label>
      </div>
      {error && <div className="settings-error" role="alert">{error}</div>}
      {status === "success" && <div className="settings-success" role="status"><Icon name="check" size={15} /> Đã đổi mật khẩu.</div>}
      <div className="settings-actions"><button className="settings-primary" type="submit" disabled={status === "saving"}>{status === "saving" ? "Đang lưu…" : "Cập nhật mật khẩu"}</button></div>
    </form>
    <section className="settings-card security-card"><div className="settings-card-header"><div><h2>Thiết bị và phiên đăng nhập</h2><p>Mỗi trình duyệt có một phiên riêng. Thu hồi ngay thiết bị bạn không còn tin cậy.</p></div><button type="button" className="settings-secondary" onClick={revokeOthers}>Thu hồi thiết bị khác</button></div>{sessionsError && <div className="settings-error" role="alert">{sessionsError}</div>}{sessionsLoading ? <div className="settings-skeleton-group"><i></i></div> : <div className="device-list">{sessions.length ? sessions.map((session) => <article className="device-row" key={session.id}><span className={`device-dot ${session.current ? "current" : ""}`}></span><div><strong>{session.user_agent}</strong><small>{session.current ? "Thiết bị hiện tại" : "Phiên khác"} · Hoạt động {session.last_seen_at ? new Date(session.last_seen_at).toLocaleString("vi-VN") : "chưa ghi nhận"}</small></div><button type="button" className="device-revoke" onClick={() => revokeSession(session)}>{session.current ? "Đăng xuất" : "Thu hồi"}</button></article>) : <p className="settings-help">Chưa có phiên đăng nhập nào đang hoạt động.</p>}</div>}</section>
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
    <div className="settings-layout"><SettingsNav section={safeSection} onNavigate={onNavigate} /><main className="settings-content" id="settings-content">{content}<p className="settings-footnote">SourceLens · Evidence-first workspace · <button type="button" onClick={() => onNavigate("/app/workspace")}>Quay lại workspace</button></p></main></div>
  </div>;
}
