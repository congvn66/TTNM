import { AppProviders } from "./providers.jsx";
import ErrorBoundary from "./ErrorBoundary.jsx";
import AuthGate from "../features/auth/AuthGate.jsx";
import AppRouter from "./AppRouter.jsx";

export default function App() {
  // Development keeps the local demo frictionless; a production build is
  // private by default unless the deployer explicitly opts out.
  const defaultAuth = import.meta.env.MODE === "production" ? "true" : "false";
  const authRequired = String(import.meta.env.VITE_AUTH_REQUIRED ?? defaultAuth).toLowerCase() === "true";
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
