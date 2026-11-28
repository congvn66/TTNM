/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../features/reader/ReaderApp.jsx", () => ({ default: () => <div data-testid="workspace-scene">workspace</div> }));
vi.mock("../features/workspace/SettingsScreen.jsx", () => ({ default: ({ section, onNavigate }) => <div data-testid="settings-scene"><span>{section}</span><button onClick={() => onNavigate("/")}>workspace</button></div> }));
vi.mock("../features/workspace/AccountOnly.jsx", () => ({ default: ({ page, openSignIn }) => <div data-testid="account-only">{page}<button onClick={() => openSignIn("register")}>Đăng ký</button></div> }));

import AppRouter from "./AppRouter.jsx";

const ACCOUNT = { id: "u", email: "a@b.vn", display_name: "A", is_guest: false };

describe("AppRouter scene transitions", () => {
  afterEach(() => { cleanup(); window.history.pushState({}, "", "/"); });

  it("renders a deep-linked preferences scene and returns to the reader at /", () => {
    window.scrollTo = vi.fn();
    window.history.pushState({}, "", "/app/settings/preferences");
    render(<AppRouter user={ACCOUNT} />);
    expect(screen.getByTestId("settings-scene")).toBeTruthy();
    expect(screen.getByText("preferences")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "workspace" }));
    expect(screen.getByTestId("workspace-scene")).toBeTruthy();
    expect(window.location.pathname).toBe("/");
  });

  it("updates the scene after browser back/forward navigation", async () => {
    window.history.pushState({}, "", "/app/settings/profile");
    render(<AppRouter user={ACCOUNT} />);
    expect(screen.getByText("profile")).toBeTruthy();
    window.history.pushState({}, "", "/app/settings/security");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(screen.getByText("security")).toBeTruthy());
  });

  it("sends an address the app does not have to the reader at /", async () => {
    window.history.pushState({}, "", "/nonexistent-page");
    render(<AppRouter user={ACCOUNT} />);
    expect(screen.getByTestId("workspace-scene")).toBeTruthy();
    await waitFor(() => expect(window.location.pathname).toBe("/"));
  });
});

describe("AppRouter without an account", () => {
  afterEach(() => { cleanup(); window.history.pushState({}, "", "/"); });

  it("tells a guest that Settings and the Library need an account, with a way to sign up", () => {
    const openSignIn = vi.fn();
    for (const path of ["/app/settings/profile", "/app/library"]) {
      window.history.pushState({}, "", path);
      render(<AppRouter user={{ id: "g", email: "", display_name: "Khách", is_guest: true }} openSignIn={openSignIn} />);
      expect(screen.getByTestId("account-only").textContent).toContain(path.includes("library") ? "library" : "settings");
      expect(screen.queryByTestId("settings-scene")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Đăng ký" }));
      cleanup();
    }
    expect(openSignIn).toHaveBeenCalledWith("register");
  });
});
