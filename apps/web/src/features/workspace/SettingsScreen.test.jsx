/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ request: requestMock }));

import SettingsScreen, { describeDevice } from "./SettingsScreen.jsx";
import { ThemeProvider } from "../theme/ThemeProvider.jsx";

describe("Settings security scene", () => {
  afterEach(() => { cleanup(); requestMock.mockReset(); });

  it("changes the password through the backend contract", async () => {
    requestMock.mockResolvedValue({ changed: true });
    render(<ThemeProvider><SettingsScreen section="security" user={{ display_name: "Reader", email: "reader@example.com" }} onNavigate={vi.fn()} /></ThemeProvider>);
    const fields = document.querySelectorAll('input[type="password"]');
    fireEvent.change(fields[0], { target: { value: "old-password" } });
    fireEvent.change(fields[1], { target: { value: "new-password" } });
    fireEvent.change(fields[2], { target: { value: "new-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Đổi mật khẩu" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Đã đổi mật khẩu"));
    expect(requestMock).toHaveBeenCalledWith("/api/v1/auth/change-password", expect.objectContaining({ method: "POST" }));
  });

  it("asks for the current password in Vietnamese instead of the browser's message", async () => {
    requestMock.mockResolvedValue({ sessions: [] });
    render(<ThemeProvider><SettingsScreen section="security" user={{ display_name: "Reader", email: "reader@example.com" }} onNavigate={vi.fn()} /></ThemeProvider>);
    expect(document.querySelector("form.security-card").noValidate).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Đổi mật khẩu" }));
    expect(screen.getByRole("alert").textContent).toBe("Nhập mật khẩu hiện tại.");
    expect(requestMock).not.toHaveBeenCalledWith("/api/v1/auth/change-password", expect.anything());
  });

  it("names a device by browser and system", () => {
    expect(describeDevice("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")).toBe("Chrome · macOS");
    expect(describeDevice("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0")).toBe("Edge · Windows");
    expect(describeDevice("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")).toBe("Safari · iOS");
    expect(describeDevice("Thiết bị không xác định")).toBe("Thiết bị không xác định");
  });

  it("applies and keeps the theme on click", () => {
    render(<ThemeProvider><SettingsScreen section="preferences" user={null} onNavigate={vi.fn()} /></ThemeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Tối" }));
    expect(localStorage.getItem("sourcelens-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Tối" }).getAttribute("aria-pressed")).toBe("true");
    expect(requestMock).not.toHaveBeenCalled();
  });
});
