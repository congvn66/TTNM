import { useCallback, useEffect, useState } from "react";
import ReaderApp from "../features/reader/ReaderApp.jsx";
import LibraryScreen from "../features/workspace/LibraryScreenV2.jsx";
import SettingsScreen from "../features/workspace/SettingsScreen.jsx";
import AccountOnly from "../features/workspace/AccountOnly.jsx";

function currentPath() {
  return `${window.location.pathname}${window.location.search}`;
}

// "/app/workspace" is the reader's older address, kept so saved links still open it.
const READER_PATHS = ["/", "/app", "/app/workspace"];
const isKnown = (pathname) => READER_PATHS.includes(pathname.replace(/\/+$/, "") || "/") || pathname.startsWith("/app/library") || pathname.startsWith("/app/settings");

/**
 * URL state is intentionally kept small and native.  It makes settings and
 * the library deep-linkable without adding a router dependency.
 */
export default function AppRouter({ user = null, onSignOut = null, startGuest = null, openSignIn = null, onUserChange = null }) {
  const [path, setPath] = useState(currentPath);

  useEffect(() => {
    const onPopState = () => setPath(currentPath());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((nextPath) => {
    const safePath = String(nextPath || "/");
    if (safePath === currentPath()) return;
    window.history.pushState({}, "", safePath);
    setPath(safePath);
    window.scrollTo?.({ top: 0, behavior: "auto" });
  }, []);

  // An address the app does not have opens the reader at "/", so the address bar says where the person is.
  const pathname = path.split("?")[0];
  const known = isKnown(pathname);
  useEffect(() => {
    if (known) return;
    window.history.replaceState({}, "", "/");
    setPath("/");
  }, [known]);

  // Settings and the Library belong to an account; a visitor or guest is told so and offered sign-in.
  const hasAccount = Boolean(user && !user.is_guest);
  const page = pathname.startsWith("/app/settings") ? "settings" : pathname.startsWith("/app/library") ? "library" : null;
  if (page && !hasAccount) {
    return <AccountOnly page={page} user={user} startGuest={startGuest} openSignIn={openSignIn} onNavigate={navigate} />;
  }
  if (page === "settings") {
    const section = pathname.split("/").filter(Boolean)[2] || "profile";
    return <SettingsScreen section={section} user={user} onSignOut={onSignOut} onNavigate={navigate} onUserChange={onUserChange} />;
  }
  if (page === "library") {
    return <LibraryScreen user={user} onSignOut={onSignOut} onNavigate={navigate} />;
  }

  return <ReaderApp user={user} onSignOut={onSignOut} onNavigate={navigate} startGuest={startGuest} openSignIn={openSignIn} />;
}
