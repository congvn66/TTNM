/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../features/reader/ReaderApp.jsx", () => ({ default: () => <div data-testid="workspace-scene">workspace</div> }));
vi.mock("../features/workspace/SettingsScreen.jsx", () => ({ default: ({ section, onNavigate }) => <div data-testid="settings-scene"><span>{section}</span><button onClick={() => onNavigate("/app/workspace")}>workspace</button></div> }));

import AppRouter from "./AppRouter.jsx";

describe("AppRouter scene transitions", () => {
  afterEach(() => { cleanup(); window.history.pushState({}, "", "/app/workspace"); });

  it("renders a deep-linked preferences scene and returns to workspace", () => {
    window.scrollTo = vi.fn();
    window.history.pushState({}, "", "/app/settings/preferences");
    render(<AppRouter user={{ id: "u", email: "a@b.vn", display_name: "A", is_guest: false }} />);
    expect(screen.getByTestId("settings-scene")).toBeTruthy();
    expect(screen.getByText("preferences")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "workspace" }));
    expect(screen.getByTestId("workspace-scene")).toBeTruthy();
    expect(window.location.pathname).toBe("/app/workspace");
  });

  it("updates the scene after browser back/forward navigation", async () => {
    window.history.pushState({}, "", "/app/settings/profile");
    render(<AppRouter user={{ id: "u", email: "a@b.vn", display_name: "A", is_guest: false }} />);
    expect(screen.getByText("profile")).toBeTruthy();
    window.history.pushState({}, "", "/app/settings/security");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(screen.getByText("security")).toBeTruthy());
  });
});

describe("AppRouter without an account", () => {
  it("opens the reader instead of Settings for a visitor or a guest", async () => {
    window.history.pushState({}, "", "/app/settings/profile");
    render(<AppRouter user={{ id: "g", email: "", display_name: "Khách", is_guest: true }} />);
    expect(screen.getByTestId("workspace-scene")).toBeTruthy();
    expect(screen.queryByTestId("settings-scene")).toBeNull();
  });
});
