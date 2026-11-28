// Tools mode can make several AI calls and read a chart on CPU.
const REQUEST_TIMEOUT_MS = 180_000;

function emitRequestMetric(metric) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("sourcelens:request", { detail: metric }));
}

// In Vite development the UI and API run on separate ports. Keep a safe
// local default so a missing .env value cannot silently send API requests to
// the Vite dev server (which produces the misleading "backend unavailable"
// screen). Production deployments can still provide VITE_API_URL or use the
// same-origin fallback.
export const API = (
  window.SOURCELENS_API
  ?? import.meta.env.VITE_API_URL
  ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : window.location.origin)
).replace(/\/$/, "");

// Text for errors the client creates itself. A server error shows the
// server's own detail.message, the single source of user text for it.
export const CLIENT_ERRORS = {
  network: "Không kết nối được. Thử lại.",
  timeout: "Không nhận được phản hồi. Thử lại.",
  unknown: "Đã xảy ra lỗi. Thử lại.",
};

function extractError(body, status) {
  const detail = body?.detail && typeof body.detail === "object" && !Array.isArray(body.detail) ? body.detail : {};
  const message = typeof detail.message === "string" && detail.message.trim() ? detail.message.trim() : CLIENT_ERRORS.unknown;
  const error = new Error(message);
  error.status = status;
  error.code = detail.code;
  error.traceId = detail.trace_id ?? detail.traceId;
  // Extra fields some errors carry, e.g. the possible readings of an ambiguous number.
  error.detail = detail;
  return error;
}

export async function request(path, options = {}) {
  const requestId = crypto.randomUUID();
  const startedAt = performance.now();
  const method = options.method ?? "GET";
  const controller = new AbortController();
  const signal = options.signal
    ? (typeof AbortSignal?.any === "function" ? AbortSignal.any([options.signal, controller.signal]) : options.signal)
    : controller.signal;
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${API}${path}`, {
      ...options,
      signal,
      credentials: "include",
      headers: { "X-Trace-Id": requestId, ...(options.headers ?? {}) },
    });
  } catch (error) {
    emitRequestMetric({ request_id: requestId, method, path, status: 0, ok: false, duration_ms: Math.round(performance.now() - startedAt), error: error?.name === "AbortError" ? "TIMEOUT" : "NETWORK_ERROR", at: new Date().toISOString() });
    throw new Error(error?.name === "AbortError" ? CLIENT_ERRORS.timeout : CLIENT_ERRORS.network);
  } finally {
    window.clearTimeout(timeout);
  }
  const body = await response.json().catch(() => ({}));
  emitRequestMetric({ request_id: requestId, method, path, status: response.status, ok: response.ok, duration_ms: Math.round(performance.now() - startedAt), response_bytes: Number(response.headers.get("content-length") ?? 0) || undefined, at: new Date().toISOString() });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("sourcelens:auth-required"));
  }
  if (!response.ok) {
    throw extractError(body, response.status);
  }
  return body;
}
