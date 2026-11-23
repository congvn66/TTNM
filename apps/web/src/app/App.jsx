import { AppProviders } from "./providers.jsx";
import ErrorBoundary from "./ErrorBoundary.jsx";
import AuthGate from "../features/auth/AuthGate.jsx";
import AppRouter from "./AppRouter.jsx";

export default function App() {
  // Development keeps the local demo frictionless; a production build is
  // private by default unless the deployer explicitly opts out.
  // The backend is configured with AUTH_REQUIRED=true for the real
  // PostgreSQL/R2 runtime. Keeping dev's implicit demo mode here allowed a
  // user to open the workspace without a cookie, then the protected PDF
  // endpoint correctly returned 401. Require the same auth contract in every
  // environment unless explicitly overridden with VITE_AUTH_REQUIRED=false.
  const defaultAuth = "true";
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
