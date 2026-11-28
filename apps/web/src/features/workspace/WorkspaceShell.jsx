import { useCallback, useEffect, useState } from "react";
import { useTheme } from "../theme/ThemeProvider.jsx";
import { Sidebar } from "../reader/Chrome.jsx";
import { Icon } from "../reader/Icon.jsx";
import { setSoundEnabled, soundEnabled } from "../reader/signals.js";
import "../reader/reader.css";
import "./workspace.css";

// Same key and rule as the reader, so the sidebar stays as the person left it when they switch pages.
const SIDEBAR_KEY = "sourcelens-sidebar";
const narrowScreen = () => Boolean(window.matchMedia?.("(max-width: 900px)").matches);
function initialSidebar() {
  if (narrowScreen()) return false;
  try { return localStorage.getItem(SIDEBAR_KEY) !== "0"; } catch { return true; }
}

/**
 * The reader's frame for the Library, Settings and the account-only notice: the same
 * sidebar (reports, Thư viện, theme, sound, account) and a slim top bar with the page name.
 * `reports` is a useReports() result; picking a report opens it in the reader.
 */
export function WorkspaceShell({ page, title, reports, user = null, guest = false, onNavigate, onSignOut = null, openSignIn = null, onUpload, actions = null, children }) {
  const { preference, setPreference } = useTheme();
  const [sound, setSound] = useState(soundEnabled);
  const [sidebarOpen, setSidebarOpenState] = useState(initialSidebar);
  const setSidebarOpen = useCallback((open) => {
    setSidebarOpenState(open);
    if (!narrowScreen()) { try { localStorage.setItem(SIDEBAR_KEY, open ? "1" : "0"); } catch { /* storage blocked */ } }
  }, []);
  useEffect(() => { document.title = `${title} · SourceLens`; return () => { document.title = "SourceLens"; }; }, [title]);

  const go = (path) => { if (narrowScreen()) setSidebarOpenState(false); onNavigate?.(path); };
  // The reader keeps the open report in the address (?r=…), and in storage for older links.
  const openReport = (id) => { reports?.select(id); go(`/?r=${encodeURIComponent(id)}`); };
  const account = user && !guest ? user : null;

  return <div className={`rd-app ws-app ws-on-${page}${sidebarOpen ? " side-open" : ""}`}>
    <a className="rd-skip" href="#main-content">Bỏ qua điều hướng</a>
    <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} reports={reports?.reports ?? []} selected={null}
      onOpen={openReport} onHome={() => { reports?.select(null); go("/"); }} onNew={onUpload ?? (() => go("/?upload=1"))}
      onLibrary={account ? () => go("/app/library") : null} libraryActive={page === "library"}
      user={account} guest={guest} onSignIn={openSignIn} onSettings={() => go("/app/settings/profile")} onSignOut={onSignOut}
      theme={preference} onTheme={setPreference} sound={sound} onSound={() => { setSoundEnabled(!sound); setSound(!sound); }} />
    <header className="rd-top ws-top">
      {!sidebarOpen && <button type="button" className="rd-icon-button" aria-label="Hiện thanh bên" title="Hiện thanh bên" onClick={() => setSidebarOpen(true)}><Icon name="sidebar" /></button>}
      <h1 className="ws-top-title">{title}</h1>
      {actions && <div className="rd-top-actions">{actions}</div>}
    </header>
    <main className="ws-main" id="main-content">{children}</main>
  </div>;
}
