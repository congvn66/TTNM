import { AppProviders } from "./providers.jsx";
import WorkspaceScreen from "../features/workspace/WorkspaceScreen.jsx";

export default function App() {
  return (
    <AppProviders>
      <WorkspaceScreen />
    </AppProviders>
  );
}
