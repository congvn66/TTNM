import { Icon } from "../reader/Icon.jsx";
import { useReports } from "../reader/useReports.js";
import { WorkspaceShell } from "./WorkspaceShell.jsx";

const PAGES = {
  library: { title: "Thư viện", heading: "Thư viện dành cho tài khoản", icon: "folder" },
  settings: { title: "Cài đặt", heading: "Cài đặt dành cho tài khoản", icon: "settings" },
};

/** What a visitor or guest sees on an account page: the reason and the way in, inside the reader's frame. */
export default function AccountOnly({ page, user = null, startGuest = null, openSignIn = null, onNavigate }) {
  const reports = useReports({ user, startGuest, syncUrl: false });
  const guest = Boolean(user?.is_guest);
  const text = PAGES[page] ?? PAGES.library;
  return <WorkspaceShell page={`${page}-locked`} title={text.title} reports={reports} user={user} guest={guest} openSignIn={openSignIn} onNavigate={onNavigate}>
    <div className="ws-page">
      <section className="ws-locked">
        <span className="ws-locked-icon" aria-hidden="true"><Icon name={text.icon} size={22} /></span>
        <h2>{text.heading}</h2>
        <p>{guest ? "Báo cáo bạn đã tải lên sẽ được chuyển vào tài khoản." : "Đăng nhập hoặc tạo tài khoản để dùng trang này."}</p>
        {openSignIn && <div className="ws-locked-actions">
          <button type="button" className="rd-button primary" onClick={() => openSignIn("login")}>Đăng nhập</button>
          <button type="button" className="rd-button" onClick={() => openSignIn("register")}>Đăng ký</button>
        </div>}
        <button type="button" className="rd-link" onClick={() => onNavigate?.("/")}>Về trang chính</button>
      </section>
    </div>
  </WorkspaceShell>;
}
