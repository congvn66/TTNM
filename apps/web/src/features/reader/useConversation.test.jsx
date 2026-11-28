/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ API: "http://localhost:8000", request: requestMock }));
import { useConversation } from "./useConversation.js";
import { friendlyError } from "./Notes.jsx";

const report = { id: "doc", sessionId: "s" };
const user = (id, body) => ({ id, role: "user", document_id: "doc", body });
const working = (id) => ({ id, role: "assistant", document_id: "doc", status: "processing", body: "" });

/** A fake server: `messages` is what GET returns; `post` answers a question. */
function server({ messages = [], post, getDelay = null } = {}) {
  const state = { messages, posts: [], cancels: [], gets: 0 };
  requestMock.mockImplementation(async (path, options = {}) => {
    if (path === "/api/v1/sessions/s") {
      state.gets += 1;
      if (getDelay) await getDelay();
      if (state.down) throw new Error("Không kết nối được. Thử lại.");
      return { session: { messages: state.messages } };
    }
    if (path === "/api/v1/sessions/s/messages") { state.posts.push(options.headers["Idempotency-Key"]); return post(state, JSON.parse(options.body)); }
    if (path === "/api/v1/jobs") return { jobs: state.jobs ?? [] };
    if (path.endsWith("/cancel")) { state.cancels.push(path); return { status: "cancelled" }; }
    return {};
  });
  return state;
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { requestMock.mockReset(); vi.restoreAllMocks(); });

it("sends a question asked before the conversation loaded once, not twice (G2-4)", async () => {
  let loadNow;
  const loaded = new Promise((resolve) => { loadNow = resolve; });
  const state = server({ getDelay: () => loaded, post: async (state, body) => {
    state.messages = [user("q", body.question), { id: "a", role: "assistant", document_id: "doc", status: "completed", body: "30" }];
    return { user_message: state.messages[0], assistant_message: state.messages[1] };
  } });
  const { result } = renderHook(() => useConversation(report));
  await act(async () => { result.current.ask("Tổng là bao nhiêu?"); });
  await act(async () => { loadNow(); });
  await waitFor(() => expect(result.current.notes).toHaveLength(1));
  expect(state.posts).toHaveLength(1);
  expect(result.current.pending).toHaveLength(0);
});

it("stops a question still being sent, then stops the job the server queued for it (F2-3)", async () => {
  let accept;
  const state = server({ post: (state, body) => new Promise((resolve) => { accept = () => {
    state.messages = [user("q", body.question), working("a")];
    resolve({ user_message: state.messages[0], assistant_message: state.messages[1], job: { id: "job-1" } });
  }; }) });
  const { result } = renderHook(() => useConversation(report));
  await waitFor(() => expect(result.current.loadedId).toBe("doc"));
  act(() => { result.current.ask("Hỏi chậm"); });
  await waitFor(() => expect(result.current.pending[0]?.status).toBe("asking"));
  expect(typeof result.current.pending[0].stop).toBe("function");
  await act(async () => { await result.current.pending[0].stop(); });
  expect(result.current.pending[0].status).toBe("stopped");
  expect(result.current.asking).toBe(false);
  await act(async () => { accept(); });
  await waitFor(() => expect(state.cancels).toEqual(["/api/v1/jobs/job-1/cancel"]));
  // The server's own card (now stopped) takes the place of the pending one.
  await waitFor(() => expect(result.current.pending).toHaveLength(0));
});

it("drops a failed question the server saved anyway, so it is not asked twice", async () => {
  server({ post: async (state, body) => {
    // A 500 without CORS headers: the server saved the question, the browser sees a network error.
    state.messages = [user("q", body.question), working("a")];
    throw new Error("Không kết nối được. Thử lại.");
  } });
  const { result } = renderHook(() => useConversation(report));
  await waitFor(() => expect(result.current.loadedId).toBe("doc"));
  await act(async () => { await result.current.ask("Doanh thu?"); });
  expect(result.current.pending).toHaveLength(0);
  expect(result.current.notes).toHaveLength(1);
});

it("says the server failed, not the network, when the server answers other requests (F2-3)", async () => {
  server({ post: async () => { throw new Error("Không kết nối được. Thử lại."); } });
  const { result } = renderHook(() => useConversation(report));
  await waitFor(() => expect(result.current.loadedId).toBe("doc"));
  await act(async () => { await result.current.ask("Doanh thu?"); });
  expect(result.current.pending[0].status).toBe("failed");
  expect(friendlyError(result.current.pending[0].errorObject)).toBe("Máy chủ gặp lỗi. Thử lại.");
});

it("keeps a failed question after a reload, and retries it with the same key (D2-12)", async () => {
  const state = server({ post: async () => { throw Object.assign(new Error("Hệ thống đang quá tải."), { status: 502, code: "AI_PROVIDER_UNAVAILABLE", detail: { provider_http_status: 429 } }); } });
  const first = renderHook(() => useConversation(report));
  await waitFor(() => expect(first.result.current.loadedId).toBe("doc"));
  await act(async () => { await first.result.current.ask("Doanh thu?"); });
  const failed = first.result.current.pending[0];
  expect(friendlyError(failed.errorObject)).toBe("Hệ thống đang quá tải.");
  first.unmount();

  const second = renderHook(() => useConversation(report));
  await waitFor(() => expect(second.result.current.pending.map((item) => [item.question, item.status])).toEqual([["Doanh thu?", "failed"]]));
  await act(async () => { await second.result.current.ask("Doanh thu?", second.result.current.pending[0].id); });
  expect(state.posts).toEqual([failed.key, failed.key]);
  expect(second.result.current.pending).toHaveLength(1);
  // Dismissing it forgets it for good.
  act(() => second.result.current.dismiss(second.result.current.pending[0].id));
  second.unmount();
  const third = renderHook(() => useConversation(report));
  await waitFor(() => expect(third.result.current.loadedId).toBe("doc"));
  expect(third.result.current.pending).toHaveLength(0);
});

it("turns a question the server took but never listed into a failed card", async () => {
  server({ post: async (state, body) => ({ user_message: user("q", body.question), assistant_message: working("a"), job: { id: "j" } }) });
  const { result } = renderHook(() => useConversation(report));
  await waitFor(() => expect(result.current.loadedId).toBe("doc"));
  await act(async () => { await result.current.ask("Doanh thu?"); });
  expect(result.current.pending[0].status).toBe("sent");
  const now = Date.now();
  vi.spyOn(Date, "now").mockReturnValue(now + 31_000);
  await act(async () => { await result.current.reload(); });
  await waitFor(() => expect(result.current.pending[0].status).toBe("failed"));
  expect(friendlyError(result.current.pending[0].errorObject)).toBe("Câu hỏi chưa được lưu. Thử lại.");
});
