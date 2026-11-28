/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ request: requestMock }));

import AuthGate, { bootFailure } from "./AuthGate.jsx";

describe("AuthGate recovery scenes", () => {
  beforeEach(() => {
    requestMock.mockReset();
    requestMock.mockImplementation((path) => path === "/api/v1/auth/me" ? Promise.reject({ status: 401 }) : Promise.resolve({ accepted: true }));
    window.history.pushState({}, "", "/forgot-password");
  });
  afterEach(cleanup);

  it("submits forgot-password and shows a non-enumerating success state", async () => {
    render(<AuthGate />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Quên mật khẩu" })).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "reader@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi liên kết" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Nếu email đã đăng ký"));
    expect(requestMock).toHaveBeenCalledWith("/api/v1/auth/forgot-password", expect.objectContaining({ method: "POST" }));
  });

  it("checks the fields itself and shows Vietnamese messages next to them", async () => {
    window.history.pushState({}, "", "/register");
    render(<AuthGate />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Đăng ký" })).toBeTruthy());
    expect(document.querySelector("form").noValidate).toBe(true);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "Đăng ký" }));
    expect(screen.getByText("Tên cần ít nhất 2 ký tự.")).toBeTruthy();
    expect(screen.getByText("Email không hợp lệ.")).toBeTruthy();
    expect(screen.getByText("Mật khẩu cần ít nhất 8 ký tự.")).toBeTruthy();
    expect(screen.getByLabelText("Tên").getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText("Tên"));
    expect(requestMock).toHaveBeenCalledTimes(1); // only the session check
  });

  it("shows one way back to sign-in on the sign-up page", async () => {
    window.history.pushState({}, "", "/register");
    render(<AuthGate />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Đăng ký" })).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Quay lại đăng nhập" })).toBeNull();
    expect(screen.getByRole("button", { name: "Đã có tài khoản? Đăng nhập" })).toBeTruthy();
  });

  it("says a short reset code is incomplete before asking the server", async () => {
    window.history.pushState({}, "", "/reset-password?token=abc");
    render(<AuthGate />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Đặt mật khẩu mới" })).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: "long-enough-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Đặt lại mật khẩu" }));
    expect(screen.getByText("Mã đặt lại chưa đủ. Dán cả mã trong email.")).toBeTruthy();
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it("confirms a new account after sign-up", async () => {
    window.history.pushState({}, "", "/register");
    requestMock.mockImplementation((path) => path === "/api/v1/auth/me" ? Promise.reject({ status: 401 }) : Promise.resolve({ user: { id: "u", display_name: "An", email: "an@example.com", is_guest: false } }));
    render(<AuthGate>{({ user }) => <p>Xin chào {user?.display_name}</p>}</AuthGate>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Đăng ký" })).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Tên"), { target: { value: "An" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "an@example.com" } });
    fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: "long-enough-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Đăng ký" }));
    await waitFor(() => expect(screen.getByText("Xin chào An")).toBeTruthy());
    expect(screen.getByRole("status").textContent).toContain("Đã tạo tài khoản");
  });

  it("names the reason when the server cannot be reached, and tries again in place", async () => {
    window.history.pushState({}, "", "/");
    requestMock.mockReset();
    requestMock.mockRejectedValueOnce(Object.assign(new Error("x"), { status: 503 }));
    requestMock.mockRejectedValueOnce({ status: 401 });
    render(<AuthGate>{() => <p>Trang chính</p>}</AuthGate>);
    await waitFor(() => expect(screen.getByText("Máy chủ đang gặp lỗi (mã 503).")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(screen.getByText("Trang chính")).toBeTruthy());
    expect(requestMock.mock.calls[0][1].signal).toBeTruthy();
  });

  it("describes a stuck or missing server", () => {
    expect(bootFailure(new Error("x"), true)).toBe("Máy chủ chưa trả lời sau 10 giây.");
    expect(bootFailure(new Error("Không kết nối được. Thử lại."), false)).toBe("Không gọi được máy chủ. Kiểm tra mạng rồi thử lại.");
  });

  it("hands a renamed user to the app", async () => {
    window.history.pushState({}, "", "/");
    requestMock.mockReset();
    requestMock.mockResolvedValue({ user: { id: "u", display_name: "Cũ", email: "a@b.vn", is_guest: false } });
    render(<AuthGate>{({ user, updateUser }) => <button onClick={() => updateUser({ display_name: "Mới" })}>{user.display_name}</button>}</AuthGate>);
    fireEvent.click(await screen.findByRole("button", { name: "Cũ" }));
    expect(screen.getByRole("button", { name: "Mới" })).toBeTruthy();
  });
});

