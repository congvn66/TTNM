/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from "vitest";
import { request } from "./client.js";

afterEach(() => vi.unstubAllGlobals());

it.each([
  ["PDF_ENCRYPTED", 422, "PDF này được đặt mật khẩu nên không đọc được. Hãy gỡ mật khẩu rồi tải lên lại."],
  ["DOCUMENT_CONTEXT_TOO_LARGE", 502, "Tài liệu quá dài để trợ lý đọc hết trong một lần hỏi."],
  ["ASSISTANT_INCOMPLETE", 502, "Trợ lý chưa hoàn tất câu trả lời trong số bước cho phép. Hãy thử lại hoặc hỏi cụ thể hơn."],
])("shows the Vietnamese message for %s", async (code, status, message) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false,
    status,
    headers: new Headers(),
    json: async () => ({ detail: { code, message: "internal English text" } }),
  }));
  await expect(request("/x")).rejects.toMatchObject({ code, message });
});
