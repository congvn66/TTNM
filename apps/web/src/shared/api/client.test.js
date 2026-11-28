/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { CLIENT_ERRORS, request, sameLoopbackName } from "./client.js";

afterEach(() => vi.unstubAllGlobals());

function respond(status, body) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status, headers: new Headers(), json: async () => body }));
}

it.each([
  ["AI_ANSWER_TIMEOUT", 504],
  ["NUMBER_FORMAT_AMBIGUOUS", 422],
  ["SOME_CODE_THE_WEB_NEVER_SAW", 500],
])("shows the server's own message for %s", async (code, status) => {
  respond(status, { detail: { code, message: "Thông báo do máy chủ viết.", readings: ["1250"] } });
  await expect(request("/x")).rejects.toMatchObject({ code, status, message: "Thông báo do máy chủ viết.", detail: { readings: ["1250"] } });
});

it.each([
  ["no message", { detail: { code: "X" } }],
  ["a plain string detail", { detail: "Not Found" }],
  ["a request-shape list", { detail: [{ loc: ["body"], msg: "field required" }] }],
  ["no body", {}],
])("uses the client's own text when the server sends %s", async (_, body) => {
  respond(422, body);
  await expect(request("/x")).rejects.toMatchObject({ status: 422, message: CLIENT_ERRORS.unknown });
});

it("uses the client's own text when the network fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
  await expect(request("/x")).rejects.toMatchObject({ message: CLIENT_ERRORS.network });
});

describe("sameLoopbackName", () => {
  it("calls a loopback API by the name the page uses", () => {
    expect(sameLoopbackName("http://127.0.0.1:8010", "localhost")).toBe("http://localhost:8010/");
    expect(sameLoopbackName("http://localhost:8010", "127.0.0.1")).toBe("http://127.0.0.1:8010/");
  });

  it("leaves other hosts alone", () => {
    expect(sameLoopbackName("https://api.example.com", "localhost")).toBe("https://api.example.com/");
    expect(sameLoopbackName("http://127.0.0.1:8010", "app.example.com")).toBe("http://127.0.0.1:8010/");
  });
});
