import { useCallback, useEffect, useState } from "react";
import { request } from "../../shared/api/client.js";
import "../reader/reader.css";

const AUTH_PATHS = ["/login", "/register", "/forgot-password", "/reset-password"];
const AFTER_LOGIN_KEY = "sourcelens-after-login";

// After signing in from a guest session: how many reports moved, shown once by the reader.
export const MOVED_KEY = "sourcelens-moved-reports";

const modeOf = (path) => (path === "/register" ? "register" : path === "/forgot-password" ? "forgot" : path === "/reset-password" ? "reset" : "login");

const ACCOUNT_PAGES = ["/app/library", "/app/settings"];

/**
 * Leave the sign-in address for the page the person came from (or the reader).
 * Without an account, an account-only page would only say "sign in" again, so it goes to the reader instead.
 */
function leaveAuthPath({ signedIn = true } = {}) {
  let target = "/";
  try { target = sessionStorage.getItem(AFTER_LOGIN_KEY) || "/"; sessionStorage.removeItem(AFTER_LOGIN_KEY); } catch { /* storage blocked */ }
  if (!signedIn && ACCOUNT_PAGES.some((page) => target.startsWith(page))) target = "/";
  window.history.replaceState({}, "", target);
  return target;
}

// The session check is small: a server that has not answered by then is down or stuck, and the person should know.
export const BOOT_TIMEOUT_MS = 10_000;

/** Why the session check failed, in words a reader understands. */
export function bootFailure(reason, timedOut) {
  if (timedOut) return "Máy chủ chưa trả lời sau 10 giây.";
  if (reason?.status >= 500) return `Máy chủ đang gặp lỗi (mã ${reason.status}).`;
  if (reason?.status) return reason.message || `Máy chủ trả lời lỗi (mã ${reason.status}).`;
  return "Không gọi được máy chủ. Kiểm tra mạng rồi thử lại.";
}

/** The reader's own start screen, so checking the session and loading reports look like one step. */
export function BootScreen({ children = "Đang tải…" }) {
  return <div className="rd-app"><div className="rd-boot" role="status"><span className="rd-spinner large" aria-hidden="true" />{children}</div></div>;
}

const initialForm = { email: "", password: "", display_name: "" };

const PASSWORD_MIN_LENGTH = 8;
// The server takes reset codes of 20 characters or more; a shorter one is a partial paste.
const RESET_CODE_MIN_LENGTH = 20;
const TITLES = { login: "Đăng nhập", register: "Đăng ký", forgot: "Quên mật khẩu", reset: "Đặt mật khẩu mới" };
const NOTES = { forgot: "Nhập email để nhận liên kết đặt lại.", reset: "Các thiết bị khác sẽ bị đăng xuất." };
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+$/;

// The fields of each mode, checked here so the messages are Vietnamese and sit
// next to their field (the browser's own messages follow the browser language).
function formErrors(mode, form) {
  const errors = {};
  if (mode === "register" && form.display_name.trim().length < 2) errors.display_name = "Tên cần ít nhất 2 ký tự.";
  if (mode !== "reset") {
    if (!form.email.trim()) errors.email = "Nhập email.";
    else if (!EMAIL_SHAPE.test(form.email.trim())) errors.email = "Email không hợp lệ.";
  }
  if (mode === "reset" && !form.token.trim()) errors.token = "Dán mã đặt lại.";
  else if (mode === "reset" && form.token.trim().length < RESET_CODE_MIN_LENGTH) errors.token = "Mã đặt lại chưa đủ. Dán cả mã trong email.";
  if (mode === "login" && !form.password) errors.password = "Nhập mật khẩu.";
  if ((mode === "register" || mode === "reset") && form.password.length < PASSWORD_MIN_LENGTH) errors.password = `Mật khẩu cần ít nhất ${PASSWORD_MIN_LENGTH} ký tự.`;
  return errors;
}

function FieldError({ id, children }) {
  return children ? <span className="auth-field-error" id={id}>{children}</span> : null;
}

/** The reader's sidebar logo. */
function AuthMark() {
  return <svg className="auth-mark" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M16 16l5 5" /><path d="M8 11h6" /></svg>;
}

/** A short confirmation after signing up, shown over the page the person returns to. */
function AuthNotice({ text, onClose }) {
  useEffect(() => {
    if (!text) return undefined;
    const timer = window.setTimeout(onClose, 6000);
    return () => window.clearTimeout(timer);
  }, [text, onClose]);
  if (!text) return null;
  return <div className="auth-toast" role="status"><span aria-hidden="true">✓</span><p>{text}</p><button type="button" aria-label="Đóng" onClick={onClose}>×</button></div>;
}

/**
 * Anyone can use the app: without a session the reader opens empty and becomes a
 * guest on the first upload (startGuest). The sign-in form shows only on its own
 * addresses (/login, /register, …), reached from the "Đăng nhập" button.
 */
export default function AuthGate({ children }) {
  const [state, setState] = useState({ status: "checking", user: null });
  const [path, setPath] = useState(window.location.pathname);
  const [mode, setMode] = useState(() => modeOf(window.location.pathname));
  const [form, setForm] = useState({ ...initialForm, token: new URLSearchParams(window.location.search).get("token") ?? "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [notice, setNotice] = useState("");
  const closeNotice = useCallback(() => setNotice(""), []);

  /** Ask the server who is signed in, giving up after BOOT_TIMEOUT_MS with the reason. */
  const checkSession = useCallback((isActive = () => true) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), BOOT_TIMEOUT_MS);
    return request("/api/v1/auth/me", { signal: controller.signal })
      .then((body) => isActive() && setState({ status: "authenticated", user: body.user }))
      .catch((reason) => {
        if (!isActive()) return;
        if (reason?.status === 401) setState({ status: "public", user: null });
        else setState({ status: "unavailable", user: null, reason: bootFailure(reason, controller.signal.aborted) });
      })
      .finally(() => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    let active = true;
    checkSession(() => active);
    return () => { active = false; };
  }, [checkSession]);

  useEffect(() => {
    const follow = () => { setPath(window.location.pathname); setMode(modeOf(window.location.pathname)); };
    window.addEventListener("popstate", follow);
    return () => window.removeEventListener("popstate", follow);
  }, []);

  const onAuthPath = AUTH_PATHS.includes(path);
  const isGuest = Boolean(state.user?.is_guest);
  // An account never sees the form; a guest sees it only when they asked for it.
  const showForm = onAuthPath && (state.status === "public" || isGuest);
  if (state.status === "authenticated" && !isGuest && onAuthPath) setPath(leaveAuthPath());
  useEffect(() => {
    if (showForm) document.title = `${TITLES[mode]} · SourceLens`;
  }, [showForm, mode]);

  /** Open the sign-in (or sign-up) form, remembering the page to come back to. */
  const openSignIn = (nextMode = "login") => {
    try { sessionStorage.setItem(AFTER_LOGIN_KEY, `${window.location.pathname}${window.location.search}`); } catch { /* storage blocked */ }
    const nextPath = nextMode === "register" ? "/register" : "/login";
    window.history.pushState({}, "", nextPath);
    setPath(nextPath); setMode(nextMode); setError(""); setSuccess(""); setFieldErrors({});
  };
  const closeForm = () => setPath(leaveAuthPath({ signedIn: state.status === "authenticated" && !isGuest }));
  /** A new display name from Settings, so the sidebar shows it at once. */
  const updateUser = useCallback((user) => { if (user) setState((current) => (current.user ? { ...current, user: { ...current.user, ...user } } : current)); }, []);

  /** Become a guest: called on the first upload, so a visitor who only looks creates nothing. */
  const startGuest = async () => {
    if (state.user) return state.user;
    const body = await request("/api/v1/auth/guest", { method: "POST" });
    setState({ status: "authenticated", user: body.user });
    return body.user;
  };

  useEffect(() => {
    const onAuthRequired = () => setState({ status: "public", user: null });
    window.addEventListener("sourcelens:auth-required", onAuthRequired);
    return () => window.removeEventListener("sourcelens:auth-required", onAuthRequired);
  }, []);

  const signOut = async () => {
    setBusy(true);
    try {
      await request("/api/v1/auth/logout", { method: "POST" });
    } finally {
      setBusy(false);
      setState({ status: "public", user: null });
      window.history.replaceState({}, "", "/");
      setPath("/");
    }
  };

  if (state.status === "checking") return <BootScreen />;
  if (!showForm && (state.status === "authenticated" || state.status === "public")) {
    const props = { user: state.user, signOut, startGuest, openSignIn, updateUser };
    return <>{typeof children === "function" ? children(props) : children}<AuthNotice text={notice} onClose={closeNotice} /></>;
  }
  if (state.status === "unavailable" || state.status === "retrying") {
    const retrying = state.status === "retrying";
    return <div className="rd-app"><div className="rd-boot" role="alert">
      <h1>Không kết nối được</h1>
      <p className="auth-boot-reason">{state.reason}</p>
      <button type="button" className="rd-button primary" disabled={retrying} onClick={() => { setState({ ...state, status: "retrying" }); checkSession(); }}>{retrying ? "Đang thử lại…" : "Thử lại"}</button>
    </div></div>;
  }

  const switchMode = (nextMode) => {
    const nextPath = nextMode === "forgot" ? "/forgot-password" : nextMode === "reset" ? "/reset-password" : nextMode === "register" ? "/register" : "/login";
    window.history.replaceState({}, "", nextPath);
    setPath(nextPath); setMode(nextMode); setError(""); setSuccess(""); setFieldErrors({});
  };

  const submit = async (event) => {
    event.preventDefault();
    const errors = formErrors(mode, form);
    setFieldErrors(errors);
    const firstInvalid = Object.keys(errors)[0];
    if (firstInvalid) { event.currentTarget.elements.namedItem(firstInvalid)?.focus(); return; }
    setBusy(true); setError("");
    try {
      if (mode === "forgot") {
        await request("/api/v1/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: form.email }) });
        setSuccess("Nếu email đã đăng ký, bạn sẽ nhận được liên kết đặt lại.");
      } else if (mode === "reset") {
        const body = await request("/api/v1/auth/reset-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: form.token, password: form.password }) });
        setState({ status: "authenticated", user: body.user });
        setPath(leaveAuthPath());
      } else {
        const body = await request(`/api/v1/auth/${mode}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mode === "register" ? form : { email: form.email, password: form.password }) });
        if (body.moved_reports) { try { sessionStorage.setItem(MOVED_KEY, String(body.moved_reports)); } catch { /* storage blocked */ } }
        if (mode === "register") setNotice("Đã tạo tài khoản");
        setState({ status: "authenticated", user: body.user });
        setPath(leaveAuthPath());
      }
    } catch (reason) {
      setError(reason.message);
    } finally { setBusy(false); }
  };

  const fieldErrorId = (name) => `auth-${name}-error`;
  // Value, change handler and error state of one form field.
  const field = (name) => ({
    name, value: form[name], "aria-required": true, "aria-invalid": Boolean(fieldErrors[name]),
    "aria-describedby": fieldErrors[name] ? fieldErrorId(name) : undefined,
    onChange: (event) => { setForm({ ...form, [name]: event.target.value }); setFieldErrors((current) => ({ ...current, [name]: "" })); },
  });

  return <main className="auth-gate">
    <section className="auth-card">
      <div className="auth-brand"><AuthMark /><strong>SourceLens</strong></div>
      <div className="auth-copy"><h1>{TITLES[mode]}</h1>{NOTES[mode] && <p className="auth-muted">{NOTES[mode]}</p>}{isGuest && (mode === "login" || mode === "register") && <p className="auth-muted">Báo cáo bạn đã tải lên sẽ được chuyển vào tài khoản.</p>}</div>
      <form className="auth-form" onSubmit={submit} noValidate>
        {mode === "register" && <label>Tên<input {...field("display_name")} placeholder="Nguyễn Văn A" /></label>}<FieldError id={fieldErrorId("display_name")}>{fieldErrors.display_name}</FieldError>
        {mode !== "reset" && <label>Email<input {...field("email")} type="email" autoComplete="email" placeholder="ten@congty.vn" /></label>}<FieldError id={fieldErrorId("email")}>{fieldErrors.email}</FieldError>
        {mode === "reset" && <label>Mã đặt lại<input {...field("token")} placeholder="Dán mã trong email" /></label>}<FieldError id={fieldErrorId("token")}>{fieldErrors.token}</FieldError>
        {mode !== "forgot" && <label>Mật khẩu<input {...field("password")} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder={mode === "login" ? undefined : `Tối thiểu ${PASSWORD_MIN_LENGTH} ký tự`} /></label>}<FieldError id={fieldErrorId("password")}>{fieldErrors.password}</FieldError>
        {error && <div className="auth-error" role="alert">{error}</div>}
        {success && <div className="auth-success" role="status">{success}</div>}
        <button className="auth-primary" type="submit" disabled={busy}>{busy ? "Đang xử lý…" : mode === "login" ? "Đăng nhập" : mode === "register" ? "Đăng ký" : mode === "forgot" ? "Gửi liên kết" : "Đặt lại mật khẩu"}</button>
      </form>
      <div className="auth-links">{mode === "login" && <button className="auth-switch secondary" onClick={() => switchMode("forgot")}>Quên mật khẩu?</button>}{(mode === "forgot" || mode === "reset") && <button className="auth-switch" onClick={() => switchMode("login")}>Quay lại đăng nhập</button>}{(mode === "login" || mode === "register") && <button className="auth-switch" onClick={() => switchMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "Chưa có tài khoản? Đăng ký" : "Đã có tài khoản? Đăng nhập"}</button>}<button className="auth-switch secondary" onClick={closeForm}>Về trang chính</button></div>
    </section>
  </main>;
}
