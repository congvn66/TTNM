/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../features/workspace/WorkspaceScreen.jsx", () => ({ default: ({ user }) => <div data-testid="workspace-scene">workspace {user?.display_name}</div> }));
vi.mock("../features/workspace/SettingsScreen.jsx", () => ({ default: ({ section, onNavigate, onUserChange }) => <div data-testid="settings-scene"><span>{section}</span><button onClick={() => onUserChange?.({ display_name: "Tên mới" })}>update profile</button><button onClick={() => onNavigate("/app/workspace")}>workspace</button></div> }));

import AppRouter from "./AppRouter.jsx";

describe("AppRouter scene transitions", () => {
  afterEach(() => { cleanup(); window.history.pushState({}, "", "/app/workspace"); });

  it("renders a deep-linked preferences scene and returns to workspace", () => {
    window.scrollTo = vi.fn();
    window.history.pushState({}, "", "/app/settings/preferences");
    render(<AppRouter />);
    expect(screen.getByTestId("settings-scene")).toBeTruthy();
    expect(screen.getByText("preferences")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "workspace" }));
    expect(screen.getByTestId("workspace-scene")).toBeTruthy();
    expect(window.location.pathname).toBe("/app/workspace");
  });

  it("updates the scene after browser back/forward navigation", async () => {
    window.history.pushState({}, "", "/app/settings/profile");
    render(<AppRouter />);
    expect(screen.getByText("profile")).toBeTruthy();
    window.history.pushState({}, "", "/app/settings/security");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(screen.getByText("security")).toBeTruthy());
  });

  it("keeps an edited profile when returning to workspace", () => {
    window.history.pushState({}, "", "/app/settings/profile");
    render(<AppRouter user={{ display_name: "Tên cũ" }} />);
    fireEvent.click(screen.getByRole("button", { name: "update profile" }));
    fireEvent.click(screen.getByRole("button", { name: "workspace" }));
    expect(screen.getByTestId("workspace-scene").textContent).toContain("Tên mới");
  });
});
