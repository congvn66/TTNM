import { useEffect, useState } from "react";
import { request } from "../../shared/api/client.js";

const initialForm = { email: "", password: "", display_name: "" };

function AuthMark() {
  return <div className="auth-mark" aria-hidden="true"><span>S</span></div>;
}

export default function AuthGate({ children }) {
  const [state, setState] = useState({ status: "checking", user: null });
  const initialMode = window.location.pathname === "/register" ? "register" : window.location.pathname === "/forgot-password" ? "forgot" : window.location.pathname === "/reset-password" ? "reset" : "login";
  const [mode, setMode] = useState(initialMode);
  const [form, setForm] = useState({ ...initialForm, token: new URLSearchParams(window.location.search).get("token") ?? "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let active = true;
    request("/api/v1/auth/me").then((body) => active && setState({ status: "authenticated", user: body.user }))
      .catch((reason) => active && setState({ status: reason?.status === 401 ? "public" : "unavailable", user: null }));
    return () => { active = false; };
  }, []);

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
      window.history.replaceState({}, "", "/login");
    }
  };

  if (state.status === "checking") return <div className="auth-loading"><div className="auth-spinner"></div><span>Đang kiểm tra phiên đăng nhập…</span></div>;
  if (state.status === "authenticated") return typeof children === "function" ? children({ user: state.user, signOut }) : children;
  if (state.status === "unavailable") return <main className="auth-gate"><section className="auth-card"><AuthMark /><p className="auth-eyebrow">SourceLens</p><h1>Chưa thể mở phiên làm việc</h1><p className="auth-muted">Dịch vụ đăng nhập hiện chưa sẵn sàng. Hãy kiểm tra kết nối rồi thử lại.</p><button className="auth-primary" onClick={() => window.location.reload()}>Thử lại</button></section></main>;

  const switchMode = (nextMode) => {
    const nextPath = nextMode === "forgot" ? "/forgot-password" : nextMode === "reset" ? "/reset-password" : "/login";
    window.history.replaceState({}, "", nextPath);
    setMode(nextMode); setError(""); setSuccess("");
  };

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      if (mode === "forgot") {
        await request("/api/v1/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: form.email }) });
        setSuccess("Nếu email tồn tại, hướng dẫn đặt lại mật khẩu đã được gửi. Kiểm tra hộp thư của bạn.");
      } else if (mode === "reset") {
        const body = await request("/api/v1/auth/reset-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: form.token, password: form.password }) });
        setState({ status: "authenticated", user: body.user });
      } else {
        const body = await request(`/api/v1/auth/${mode}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mode === "register" ? form : { email: form.email, password: form.password }) });
        setState({ status: "authenticated", user: body.user });
      }
    } catch (reason) {
      setError(reason.message || "Không thể xác thực. Hãy thử lại.");
    } finally { setBusy(false); }
  };

  return <main className="auth-gate">
    <section className="auth-card">
      <div className="auth-brand"><AuthMark /><div><strong>SourceLens</strong><span>Evidence-first workspace</span></div></div>
      <div className="auth-copy"><p className="auth-eyebrow">{mode === "login" ? "Chào mừng trở lại" : mode === "register" ? "Tạo workspace riêng" : mode === "forgot" ? "Khôi phục tài khoản" : "Đặt lại mật khẩu"}</p><h1>{mode === "login" ? "Đăng nhập vào tài liệu của bạn" : mode === "register" ? "Bắt đầu với SourceLens" : mode === "forgot" ? "Lấy lại quyền truy cập" : "Chọn mật khẩu mới"}</h1><p className="auth-muted">{mode === "forgot" ? "Nhập email đã đăng ký. Chúng tôi sẽ gửi hướng dẫn an toàn nếu tìm thấy tài khoản." : mode === "reset" ? "Mật khẩu mới sẽ đăng xuất các phiên đang hoạt động để bảo vệ tài khoản." : "Tổ chức PDF, hỏi AI có căn cứ và giữ lại mọi nguồn dẫn theo từng phiên."}</p></div>
      <form className="auth-form" onSubmit={submit}>
        {mode === "register" && <label>Tên hiển thị<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} placeholder="Nguyễn Văn A" minLength={2} required /></label>}
        {mode !== "reset" && <label>Email<input type="email" autoComplete="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} placeholder="you@example.com" required /></label>}
        {mode === "reset" && <label>Mã đặt lại<input value={form.token} onChange={(event) => setForm({ ...form, token: event.target.value })} placeholder="Dán mã trong email" required /></label>}
        {mode !== "forgot" && <label>Mật khẩu<input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} placeholder="Tối thiểu 8 ký tự" minLength={8} required /></label>}
        {error && <div className="auth-error" role="alert">{error}</div>}
        {success && <div className="auth-success" role="status">{success}</div>}
        <button className="auth-primary" type="submit" disabled={busy}>{busy ? "Đang xử lý…" : mode === "login" ? "Đăng nhập" : mode === "register" ? "Tạo tài khoản" : mode === "forgot" ? "Gửi hướng dẫn" : "Đặt lại mật khẩu"}</button>
      </form>
      <div className="auth-links">{mode === "login" && <button className="auth-switch secondary" onClick={() => switchMode("forgot")}>Quên mật khẩu?</button>}{mode !== "login" && <button className="auth-switch" onClick={() => switchMode("login")}>Quay lại đăng nhập</button>}{(mode === "login" || mode === "register") && <button className="auth-switch" onClick={() => switchMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "Chưa có tài khoản? Tạo tài khoản" : "Đã có tài khoản? Đăng nhập"}</button>}</div>
      <small className="auth-footnote">Cookie phiên được bảo vệ ở phía máy chủ · Không lưu mật khẩu trong trình duyệt</small>
    </section>
  </main>;
}
