import { ThemeProvider } from "../features/theme/ThemeProvider.jsx";

export function AppProviders({ children }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}
