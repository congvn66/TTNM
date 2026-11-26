/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ request: requestMock }));

import SettingsScreen from "./SettingsScreen.jsx";
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
    fireEvent.click(screen.getByRole("button", { name: "Cập nhật mật khẩu" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Đã đổi mật khẩu"));
    expect(requestMock).toHaveBeenCalledWith("/api/v1/auth/change-password", expect.objectContaining({ method: "POST" }));
  });

  it("asks for the current password in Vietnamese instead of the browser's message", async () => {
    requestMock.mockResolvedValue({ sessions: [] });
    render(<ThemeProvider><SettingsScreen section="security" user={{ display_name: "Reader", email: "reader@example.com" }} onNavigate={vi.fn()} /></ThemeProvider>);
    expect(document.querySelector("form.security-card").noValidate).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Cập nhật mật khẩu" }));
    expect(screen.getByRole("alert").textContent).toBe("Hãy nhập mật khẩu hiện tại.");
    expect(requestMock).not.toHaveBeenCalledWith("/api/v1/auth/change-password", expect.anything());
  });
});
