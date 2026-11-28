/** @vitest-environment jsdom */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client.js", () => ({ request: vi.fn() }));
import { request } from "../../shared/api/client.js";
import { useReports } from "./useReports.js";

const SESSIONS = { sessions: [{ id: "s1", title: "Báo cáo của tôi", documents: [{ id: "d1", file_name: "a.pdf", extraction_status: "ready", created_at: "2026-11-28" }] }] };

afterEach(() => { localStorage.clear(); window.history.replaceState({}, "", "/"); vi.clearAllMocks(); });

describe("useReports remembered report", () => {
  it("drops a remembered report this account does not have, without a message", async () => {
    localStorage.setItem("sourcelens-report-v2", "other-account-doc");
    request.mockResolvedValue(SESSIONS);
    const { result } = renderHook(() => useReports({ user: { id: "u1" } }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await waitFor(() => expect(localStorage.getItem("sourcelens-report-v2")).toBeNull(), { timeout: 4000 });
    expect(result.current.lost).toBeNull();
    expect(result.current.selected).toBeNull();
  });

  it("says so when the address asks for a report that is not there", async () => {
    window.history.replaceState({}, "", "/?r=gone-doc");
    request.mockResolvedValue(SESSIONS);
    const { result } = renderHook(() => useReports({ user: { id: "u1" } }));
    await waitFor(() => expect(result.current.lost).toBe(""), { timeout: 4000 });
  });
});
