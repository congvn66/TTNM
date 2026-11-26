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

const ERROR_MESSAGES = {
  PDF_ENCRYPTED: "PDF này được đặt mật khẩu nên không đọc được. Hãy gỡ mật khẩu rồi tải lên lại.",
  AI_PROVIDER_UNAVAILABLE: "Dịch vụ AI đang bận hoặc tạm thời không phản hồi. Hãy thử lại sau ít phút.",
  AI_PROVIDER_TIMEOUT: "Dịch vụ AI phản hồi quá lâu. Bạn có thể thử lại câu hỏi.",
  AI_MODEL_UNAVAILABLE: "Mô hình AI hiện không khả dụng. Kiểm tra lại cấu hình model.",
  AI_PROVIDER_HTTP_ERROR: "Dịch vụ AI từ chối yêu cầu. Kiểm tra API key và giới hạn sử dụng.",
  AI_NOT_CONFIGURED: "Chưa cấu hình nhà cung cấp AI cho môi trường này.",
  AI_INVALID_OUTPUT: "AI trả về dữ liệu không đúng định dạng. Hãy thử lại câu hỏi.",
  AI_UNGROUNDED_CITATION: "AI trả về trích dẫn không nằm trong tài liệu. Hãy thử lại câu hỏi.",
  AI_UNSUPPORTED_EVIDENCE: "AI chưa xác minh được evidence trong tài liệu. Hãy thử lại câu hỏi.",
  DOCUMENT_CONTEXT_TOO_LARGE: "Tài liệu quá dài để trợ lý đọc hết trong một lần hỏi.",
  ASSISTANT_INCOMPLETE: "Trợ lý chưa hoàn tất câu trả lời trong số bước cho phép. Hãy thử lại hoặc hỏi cụ thể hơn.",
  QUEUE_UNAVAILABLE: "Hàng đợi xử lý chưa sẵn sàng. Hãy khởi động worker hoặc thử lại sau.",
  DATABASE_UNAVAILABLE: "Dịch vụ dữ liệu tạm thời không sẵn sàng. Hãy thử lại sau.",
};

function extractError(body, status) {
  const detail = body?.detail ?? body;
  const code = detail && typeof detail === "object" ? detail.code : undefined;
  const message = detail && typeof detail === "object" ? detail.message : detail;
  const fallback = typeof message === "string" && message.trim() ? message : `HTTP ${status}`;
  const error = new Error(code && ERROR_MESSAGES[code] ? ERROR_MESSAGES[code] : fallback);
  error.status = status;
  error.code = code;
  error.traceId = detail && typeof detail === "object" ? (detail.trace_id ?? detail.traceId) : undefined;
  error.rawMessage = fallback;
  // Extra fields some errors carry, e.g. the possible readings of an ambiguous number.
  error.detail = detail && typeof detail === "object" ? detail : undefined;
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
    throw extractError(body, response.status);
  }
  return body;
}
