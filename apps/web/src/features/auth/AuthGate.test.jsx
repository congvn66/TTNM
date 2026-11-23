/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ request: requestMock }));

import AuthGate from "./AuthGate.jsx";

describe("AuthGate recovery scenes", () => {
  beforeEach(() => {
    requestMock.mockReset();
    requestMock.mockImplementation((path) => path === "/api/v1/auth/me" ? Promise.reject({ status: 401 }) : Promise.resolve({ accepted: true }));
    window.history.pushState({}, "", "/forgot-password");
  });
  afterEach(cleanup);

  it("submits forgot-password and shows a non-enumerating success state", async () => {
    render(<AuthGate />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Lấy lại quyền truy cập" })).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "reader@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi hướng dẫn" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Nếu email tồn tại"));
    expect(requestMock).toHaveBeenCalledWith("/api/v1/auth/forgot-password", expect.objectContaining({ method: "POST" }));
  });

  it("keeps the register form deep-linkable", async () => {
    window.history.pushState({}, "", "/login");
    render(<AuthGate />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Đăng nhập vào tài liệu của bạn" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Chưa có tài khoản? Tạo tài khoản" }));
    expect(window.location.pathname).toBe("/register");
    expect(screen.getByRole("heading", { name: "Bắt đầu với SourceLens" })).toBeTruthy();
  });

  it("moves authenticated users to the workspace URL", async () => {
    window.history.pushState({}, "", "/login");
    requestMock.mockImplementation((path) => path === "/api/v1/auth/me"
      ? Promise.reject({ status: 401 })
      : Promise.resolve({ user: { email: "reader@example.com" } }));
    render(<AuthGate>{() => <div>Workspace ready</div>}</AuthGate>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Đăng nhập vào tài liệu của bạn" })).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: "password-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    await waitFor(() => expect(screen.getByText("Workspace ready")).toBeTruthy());
    expect(window.location.pathname).toBe("/app/workspace");
  });
});
