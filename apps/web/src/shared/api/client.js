const REQUEST_TIMEOUT_MS = 90_000;

function emitRequestMetric(metric) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("sourcelens:request", { detail: metric }));
}

export const API = (window.SOURCELENS_API ?? import.meta.env.VITE_API_URL ?? window.location.origin).replace(/\/$/, "");

export async function request(path, options = {}) {
  const requestId = crypto.randomUUID();
  const startedAt = performance.now();
  const method = options.method ?? "GET";
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${API}${path}`, {
      ...options,
      signal: options.signal ?? controller.signal,
      credentials: "include",
      headers: { "X-Trace-Id": crypto.randomUUID(), ...(options.headers ?? {}) },
    });
  } catch (error) {
    emitRequestMetric({ request_id: requestId, method, path, status: 0, ok: false, duration_ms: Math.round(performance.now() - startedAt), error: error?.name === "AbortError" ? "TIMEOUT" : "NETWORK_ERROR", at: new Date().toISOString() });
    if (error?.name === "AbortError") throw new Error("Yêu cầu quá thời gian chờ. Hãy thử lại.");
    throw new Error(`Không kết nối được tới backend tại ${API}. Kiểm tra API rồi thử lại.`);
  } finally {
    window.clearTimeout(timeout);
  }
  const body = await response.json().catch(() => ({}));
  emitRequestMetric({ request_id: requestId, method, path, status: response.status, ok: response.ok, duration_ms: Math.round(performance.now() - startedAt), response_bytes: Number(response.headers.get("content-length") ?? 0) || undefined, at: new Date().toISOString() });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("sourcelens:auth-required"));
  }
  if (!response.ok) {
    const detail = body.detail;
    const error = new Error(detail && typeof detail === "object" ? `${detail.code ? `${detail.code}: ` : ""}${detail.message ?? `HTTP ${response.status}`}` : (detail ?? `HTTP ${response.status}`));
    error.status = response.status;
    error.code = detail && typeof detail === "object" ? detail.code : undefined;
    throw error;
  }
  return body;
}
