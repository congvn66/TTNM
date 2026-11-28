import { useEffect, useState } from "react";
import { request } from "../../shared/api/client.js";
import "../reader/reader.css";

const AUTH_PATHS = ["/login", "/register", "/forgot-password", "/reset-password"];
const AFTER_LOGIN_KEY = "sourcelens-after-login";

// After signing in from a guest session: how many reports moved, shown once by the reader.
export const MOVED_KEY = "sourcelens-moved-reports";

const modeOf = (path) => (path === "/register" ? "register" : path === "/forgot-password" ? "forgot" : path === "/reset-password" ? "reset" : "login");

/** Leave the sign-in address for the page the person came from (or the reader). */
function leaveAuthPath() {
  let target = "/";
  try { target = sessionStorage.getItem(AFTER_LOGIN_KEY) || "/"; sessionStorage.removeItem(AFTER_LOGIN_KEY); } catch { /* storage blocked */ }
  window.history.replaceState({}, "", target);
  return target;
}

/** The reader's own start screen, so checking the session and loading reports look like one step. */
export function BootScreen({ children = "Đang tải…" }) {
  return <div className="rd-app"><div className="rd-boot" role="status"><span className="rd-spinner large" aria-hidden="true" />{children}</div></div>;
}

const initialForm = { email: "", password: "", display_name: "" };

const PASSWORD_MIN_LENGTH = 8;
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
  if (mode === "login" && !form.password) errors.password = "Nhập mật khẩu.";
  if ((mode === "register" || mode === "reset") && form.password.length < PASSWORD_MIN_LENGTH) errors.password = `Mật khẩu cần ít nhất ${PASSWORD_MIN_LENGTH} ký tự.`;
  return errors;
}

function FieldError({ id, children }) {
  return children ? <span className="auth-field-error" id={id}>{children}</span> : null;
}

function AuthMark() {
  return <div className="auth-mark" aria-hidden="true"><span>S</span></div>;
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

  useEffect(() => {
    let active = true;
    request("/api/v1/auth/me").then((body) => active && setState({ status: "authenticated", user: body.user }))
      .catch((reason) => active && setState({ status: reason?.status === 401 ? "public" : "unavailable", user: null }));
    return () => { active = false; };
  }, []);

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
  const closeForm = () => setPath(leaveAuthPath());

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
    const props = { user: state.user, signOut, startGuest, openSignIn };
    return typeof children === "function" ? children(props) : children;
  }
  if (state.status === "unavailable") return <main className="auth-gate"><section className="auth-card"><AuthMark /><h1>Không kết nối được</h1><button className="auth-primary" onClick={() => window.location.reload()}>Thử lại</button></section></main>;

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
      <div className="auth-brand"><AuthMark /><div><strong>SourceLens</strong></div></div>
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
      <div className="auth-links">{mode === "login" && <button className="auth-switch secondary" onClick={() => switchMode("forgot")}>Quên mật khẩu?</button>}{mode !== "login" && <button className="auth-switch" onClick={() => switchMode("login")}>Quay lại đăng nhập</button>}{(mode === "login" || mode === "register") && <button className="auth-switch" onClick={() => switchMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "Chưa có tài khoản? Đăng ký" : "Đã có tài khoản? Đăng nhập"}</button>}<button className="auth-switch secondary" onClick={closeForm}>Về trang chính</button></div>
    </section>
  </main>;
}
