import { AppProviders } from "./providers.jsx";
import ErrorBoundary from "./ErrorBoundary.jsx";
import AuthGate from "../features/auth/AuthGate.jsx";
import AppRouter from "./AppRouter.jsx";

export default function App() {
  const authRequired = String(import.meta.env.VITE_AUTH_REQUIRED ?? "false").toLowerCase() === "true";
  return (
    <AppProviders>
      <ErrorBoundary><AuthGateEnabled required={authRequired} /></ErrorBoundary>
    </AppProviders>
  );
}

function AuthGateEnabled({ required }) {
  return required
    ? <AuthGate>{({ user, signOut }) => <AppRouter user={user} onSignOut={signOut} />}</AuthGate>
    : <AppRouter />;
}
