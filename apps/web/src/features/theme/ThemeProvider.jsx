import { createContext, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "sourcelens-theme";
const ThemeContext = createContext(null);

function readPreference() {
  const value = window.localStorage.getItem(STORAGE_KEY);
  return ["light", "dark", "system"].includes(value) ? value : "system";
}

function resolveTheme(preference) {
  if (preference !== "system") return preference;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(readPreference);
  const [resolvedTheme, setResolvedTheme] = useState(() => resolveTheme(preference));

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = () => setResolvedTheme(resolveTheme(preference));
    apply();
    media?.addEventListener?.("change", apply);
    return () => media?.removeEventListener?.("change", apply);
  }, [preference]);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.style.colorScheme = resolvedTheme;
    window.localStorage.setItem(STORAGE_KEY, preference);
  }, [preference, resolvedTheme]);

  const value = useMemo(() => ({ preference, resolvedTheme, setPreference }), [preference, resolvedTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
