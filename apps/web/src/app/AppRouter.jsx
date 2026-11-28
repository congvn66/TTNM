import { useCallback, useEffect, useState } from "react";
import ReaderApp from "../features/reader/ReaderApp.jsx";
import LibraryScreen from "../features/workspace/LibraryScreenV2.jsx";
import SettingsScreen from "../features/workspace/SettingsScreen.jsx";

function currentPath() {
  return `${window.location.pathname}${window.location.search}`;
}

/**
 * URL state is intentionally kept small and native.  It makes settings and
 * workspace deep-linkable without adding a router dependency before the API
 * resources have stable route contracts.
 */
export default function AppRouter({ user = null, onSignOut = null, startGuest = null, openSignIn = null }) {
  const [path, setPath] = useState(currentPath);

  useEffect(() => {
    const onPopState = () => setPath(currentPath());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((nextPath) => {
    const safePath = String(nextPath || "/app/workspace");
    if (safePath === currentPath()) return;
    window.history.pushState({}, "", safePath);
    setPath(safePath);
    window.scrollTo?.({ top: 0, behavior: "auto" });
  }, []);

  // Settings and the Library belong to an account; a visitor or guest gets the reader.
  const hasAccount = Boolean(user && !user.is_guest);
  if (path.startsWith("/app/settings") && hasAccount) {
    const section = path.split("/").filter(Boolean)[2] || "profile";
    return <SettingsScreen section={section} user={user} onSignOut={onSignOut} onNavigate={navigate} />;
  }

  if (path.startsWith("/app/library") && hasAccount) {
    return <LibraryScreen onNavigate={navigate} />;
  }

  return <ReaderApp user={user} onSignOut={onSignOut} onNavigate={navigate} startGuest={startGuest} openSignIn={openSignIn} />;
}
