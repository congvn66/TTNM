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

  it("checks the fields itself and shows Vietnamese messages next to them", async () => {
    window.history.pushState({}, "", "/register");
    render(<AuthGate />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Bắt đầu với SourceLens" })).toBeTruthy());
    expect(document.querySelector("form").noValidate).toBe(true);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "Tạo tài khoản" }));
    expect(screen.getByText("Hãy nhập tên hiển thị, ít nhất 2 ký tự.")).toBeTruthy();
    expect(screen.getByText("Email chưa đúng dạng, ví dụ ten@congty.vn.")).toBeTruthy();
    expect(screen.getByText("Mật khẩu cần ít nhất 8 ký tự.")).toBeTruthy();
    expect(screen.getByLabelText("Tên hiển thị").getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText("Tên hiển thị"));
    expect(requestMock).toHaveBeenCalledTimes(1); // only the session check
  });
});
