/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ request: requestMock }));
// The sidebar's report list is the reader's concern; Settings only passes it through.
vi.mock("../reader/useReports.js", () => ({ useReports: () => ({ reports: [], select: vi.fn(), reload: vi.fn() }) }));

import SettingsScreen from "./SettingsScreen.jsx";
import { ThemeProvider } from "../theme/ThemeProvider.jsx";

const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const renderSettings = (props) => render(<ThemeProvider><SettingsScreen user={{ display_name: "Reader", email: "reader@example.com" }} onNavigate={vi.fn()} {...props} /></ThemeProvider>);

describe("Settings", () => {
  afterEach(() => { cleanup(); requestMock.mockReset(); });

  it("changes the password through the backend contract", async () => {
    requestMock.mockImplementation((path) => Promise.resolve(path === "/api/v1/auth/sessions" ? { sessions: [] } : { changed: true }));
    renderSettings({ section: "security" });
    const fields = document.querySelectorAll('input[type="password"]');
    fireEvent.change(fields[0], { target: { value: "old-password" } });
    fireEvent.change(fields[1], { target: { value: "new-password" } });
    fireEvent.change(fields[2], { target: { value: "new-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Đổi mật khẩu" }));
    await waitFor(() => expect(screen.getByText("Đã đổi mật khẩu.")).toBeTruthy());
    expect(requestMock).toHaveBeenCalledWith("/api/v1/auth/change-password", expect.objectContaining({ method: "POST" }));
  });

  it("asks for the current password in Vietnamese instead of the browser's message", async () => {
    requestMock.mockResolvedValue({ sessions: [] });
    renderSettings({ section: "security" });
    expect(document.querySelector("form.security-card").noValidate).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Đổi mật khẩu" }));
    expect(screen.getByRole("alert").textContent).toBe("Nhập mật khẩu hiện tại.");
    expect(requestMock).not.toHaveBeenCalledWith("/api/v1/auth/change-password", expect.anything());
  });

  it("groups many sign-ins of one device and shows five rows before Xem thêm", async () => {
    const sessions = [{ id: "me", user_agent: MAC, current: true, last_seen_at: "2026-11-28T10:00:00Z" },
      ...Array.from({ length: 40 }, (_, index) => ({ id: `mac-${index}`, user_agent: MAC, last_seen_at: "2026-11-28T09:00:00Z" })),
      { id: "script", user_agent: "python-requests/2.34.2", last_seen_at: "2026-11-28T08:00:00Z" },
      ...["Windows NT 10.0", "Linux x86_64", "Android 14", "iPhone; CPU iPhone OS 18_0 like Mac OS X"].map((system, index) => ({ id: `x-${index}`, user_agent: `Mozilla/5.0 (${system}) Firefox/130.0`, last_seen_at: "2026-11-27T08:00:00Z" }))];
    requestMock.mockResolvedValue({ sessions });
    renderSettings({ section: "security" });
    await waitFor(() => expect(document.querySelectorAll(".ws-devices li").length).toBe(5));
    expect(screen.getByText("40 lần đăng nhập", { exact: false })).toBeTruthy();
    expect(screen.getByText("Thiết bị khác")).toBeTruthy();
    expect(document.body.textContent).not.toContain("python-requests");
    fireEvent.click(screen.getByRole("button", { name: "Xem thêm 2 thiết bị" }));
    expect(document.querySelectorAll(".ws-devices li").length).toBe(7);
  });

  it("hands the saved name up, so the sidebar shows it without a reload", async () => {
    requestMock.mockResolvedValue({ user: { display_name: "Reader Two", email: "reader@example.com" } });
    const onUserChange = vi.fn();
    renderSettings({ section: "profile", onUserChange });
    fireEvent.change(screen.getByLabelText("Tên"), { target: { value: "Reader Two" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(onUserChange).toHaveBeenCalledWith(expect.objectContaining({ display_name: "Reader Two" })));
  });

  it("applies and keeps the theme on click, and names the page in the tab", () => {
    renderSettings({ section: "preferences", user: { display_name: "Reader", email: "r@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Tối" }));
    expect(localStorage.getItem("sourcelens-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Tối" }).getAttribute("aria-pressed")).toBe("true");
    expect(requestMock).not.toHaveBeenCalled();
    expect(document.title).toBe("Cài đặt · SourceLens");
  });
});
