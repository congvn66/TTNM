"""The one place for the text the server shows users.

Every error response is ``{"detail": {"code": CODE, "message": MESSAGES[CODE], ...}}``.
The code is for programs and never changes; the message is Vietnamese text
for the user, and clients show it as it is.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


MESSAGES = {
    # Request and server
    "REQUEST_INVALID": "Dữ liệu đã nhập không hợp lệ.",
    "NOT_FOUND": "Không tìm thấy trang này.",
    "METHOD_NOT_ALLOWED": "Thao tác này không được hỗ trợ.",
    "HTTP_ERROR": "Đã xảy ra lỗi. Thử lại.",
    "INTERNAL_ERROR": "Đã xảy ra lỗi. Thử lại sau.",
    "INVALID_IDEMPOTENCY_KEY": "Yêu cầu không hợp lệ. Tải lại trang.",
    "IDEMPOTENCY_KEY_REUSED": "Yêu cầu không hợp lệ. Tải lại trang.",
    # Reports
    "SESSION_NOT_FOUND": "Không tìm thấy báo cáo.",
    "SESSION_TITLE_REQUIRED": "Nhập tên báo cáo.",
    "DOCUMENT_NOT_FOUND": "Không tìm thấy báo cáo.",
    "DOCUMENT_NAME_INVALID": "Tên báo cáo không hợp lệ.",
    "DOCUMENT_FILE_MISSING": "Không tìm thấy tệp PDF của báo cáo này.",
    "MESSAGE_TRACE_NOT_FOUND": "Không tìm thấy chi tiết của câu trả lời này.",
    "FORMULA_NOT_FOUND": "Không tìm thấy phép tính này trong câu trả lời.",
    "FORMULA_NOT_RECALCULABLE": "Phép tính này không tính lại được với ô khác.",
    "FORMULA_SWAP_INVALID": "Ô cần đổi không có trong phép tính, hoặc ô mới không có trong báo cáo.",
    "RECALCULATE_BUSY": "Đang tính lại. Thử lại sau giây lát.",
    # Uploads
    "UPLOAD_FORM_INVALID": "Tên tệp quá dài (tối đa 255 ký tự).",
    "PDF_REQUIRED": "Chỉ nhận tệp PDF.",
    "INVALID_PDF": "Không đọc được tệp PDF này.",
    "EMPTY_PDF": "Tệp PDF rỗng.",
    "PDF_TOO_LARGE": "Tệp lớn hơn {max_mib} MB.",
    "PDF_TOO_MANY_PAGES": "Tệp dài hơn {max_pages} trang.",
    "PDF_ENCRYPTED": "Tệp PDF có mật khẩu. Gỡ mật khẩu rồi tải lên lại.",
    "OBJECT_STORAGE_UNAVAILABLE": "Không lưu được tệp. Thử lại sau.",
    # Reading
    "EXTRACTION_NOT_READY": "Báo cáo chưa đọc xong. Thử lại sau.",
    "EXTRACTION_IN_PROGRESS": "Báo cáo đang được đọc.",
    "EXTRACTION_UPGRADE_FAILED": "Không mở được kết quả đọc cũ. Đọc lại báo cáo.",
    "REEXTRACTION_NOT_SUPPORTED": "Chưa đọc lại được báo cáo này. Tải lên lại tệp PDF.",
    # Numbers
    "EVIDENCE_NOT_FOUND": "Không tìm thấy số liệu trong báo cáo.",
    "EVIDENCE_REVISION_CONFLICT": "Số này vừa được sửa. Tải lại trang.",
    "VALUE_UNCHANGED": "Giá trị mới trùng giá trị hiện tại.",
    "INVALID_DECIMAL": "Không đọc được số này.",
    # The document's format is unknown here, so the example has no thousands separator.
    "NUMBER_FORMAT_AMBIGUOUS": "Không đọc được \"{text}\". Ví dụ: 21500 hoặc 21,5.",
    # Answers
    "NO_TEXT_EVIDENCE": "Không tìm thấy nội dung liên quan trong báo cáo. Thử dùng từ có trong báo cáo.",
    "CHART_EVIDENCE_PERSISTENCE_FAILED": "Không trả lời được. Thử lại.",
    "AI_PROVIDER_UNAVAILABLE": "Hệ thống đang quá tải. Thử lại sau vài phút.",
    "AI_PROVIDER_TIMEOUT": "Không trả lời được. Thử lại.",
    "AI_MODEL_UNAVAILABLE": "Không trả lời được. Thử lại.",
    "AI_PROVIDER_HTTP_ERROR": "Không trả lời được. Thử lại.",
    "AI_NOT_CONFIGURED": "Tính năng này chưa bật.",
    "AI_INVALID_OUTPUT": "Không trả lời được. Thử lại.",
    "AI_UNGROUNDED_CITATION": "Không trả lời được. Thử lại.",
    "AI_UNSUPPORTED_EVIDENCE": "Không trả lời được. Thử lại.",
    "DOCUMENT_CONTEXT_TOO_LARGE": "Câu hỏi quá dài. Thử hỏi ngắn hơn.",
    "BRIEF_UNAVAILABLE": "Tính năng này chưa bật.",
    "ASSISTANT_INCOMPLETE": "Câu hỏi quá dài. Thử hỏi ngắn hơn.",
    "AI_PROVIDER_BAD_RESPONSE": "Không trả lời được. Thử lại.",
    "AI_ANSWER_TIMEOUT": "Câu hỏi quá dài. Thử hỏi ngắn hơn.",
    "AI_FAILED": "Không trả lời được. Thử lại.",
    # Background jobs
    "DURABLE_QUEUE_DISABLED": "Tính năng này chưa bật.",
    "QUEUE_UNAVAILABLE": "Hệ thống đang bận. Thử lại sau.",
    "JOB_NOT_FOUND": "Không tìm thấy tác vụ.",
    "JOB_NOT_CANCELLABLE": "Chỉ hủy được tác vụ đang chờ hoặc đang chạy.",
    "JOB_NOT_RETRYABLE": "Chỉ chạy lại được tác vụ đã lỗi.",
    # Library
    "LIBRARY_REQUIRES_POSTGRES": "Tính năng này chưa bật.",
    "PROJECT_NOT_FOUND": "Không tìm thấy dự án.",
    "PROJECT_NAME_CONFLICT": "Tên dự án đã tồn tại.",
    "PROJECT_NOT_EMPTY": "Dự án còn báo cáo. Chuyển hoặc xóa các báo cáo trước.",
    "PROJECT_DOCUMENT_NOT_FOUND": "Báo cáo không nằm trong dự án này.",
    "PROJECT_DOCUMENT_REVISION_CONFLICT": "Báo cáo vừa được thay đổi. Tải lại trang.",
    "INVALID_FOLDER_PARENT": "Thư mục cha không thuộc dự án này.",
    "FOLDER_NAME_CONFLICT": "Tên thư mục đã tồn tại.",
    "FOLDER_NOT_FOUND": "Không tìm thấy thư mục.",
    "FOLDER_REVISION_CONFLICT": "Thư mục vừa được thay đổi. Tải lại trang.",
    "FOLDER_CYCLE": "Không đặt được thư mục vào chính nó.",
    # Accounts
    "AUTH_REQUIRES_POSTGRES": "Tính năng này chưa bật.",
    "INVALID_EMAIL": "Email không hợp lệ.",
    "CSRF_ORIGIN_REJECTED": "Yêu cầu không hợp lệ. Tải lại trang.",
    "AUTH_REQUIRED": "Đăng nhập để tiếp tục.",
    "GUEST_LIMIT": "Có quá nhiều lượt dùng thử từ mạng này. Thử lại sau một giờ.",
    "GUEST_UPLOAD_LIMIT": "Khách tải lên tối đa 3 báo cáo mỗi ngày. Đăng nhập để tải thêm.",
    "GUEST_EXPIRED": "Phiên dùng thử đã hết hạn. Tải lại trang rồi tạo tài khoản.",
    "EMAIL_ALREADY_REGISTERED": "Không tạo được tài khoản với thông tin này.",
    "INVALID_CREDENTIALS": "Email hoặc mật khẩu không đúng.",
    "RESET_TOKEN_INVALID": "Liên kết đặt lại không hợp lệ hoặc đã hết hạn.",
    "PASSWORD_UNCHANGED": "Mật khẩu mới phải khác mật khẩu hiện tại.",
    "CURRENT_PASSWORD_INVALID": "Mật khẩu hiện tại không đúng.",
    "AUTH_SESSION_NOT_FOUND": "Không tìm thấy thiết bị.",
    "AUTH_DATABASE_UNAVAILABLE": "Không tải được tài khoản. Thử lại sau.",
}

# Why a typed number was refused. Each is sent as the message of INVALID_DECIMAL.
NUMBER_INPUT_MESSAGES = {
    "empty": "Nhập một số.",
    "exponent": "Không dùng dạng số mũ như 1e5. Nhập đủ các chữ số.",
    "percent": "Số này không phải phần trăm. Bỏ dấu %.",
    "too_many_digits": "Số quá dài (tối đa {limit} chữ số).",
    "not_exact": "Nhập số, ví dụ 58 hoặc 58,25.",
    "format_vi": "Không đọc được \"{text}\". Ví dụ: 21.500 hoặc 21,5.",
    "format_en": "Không đọc được \"{text}\". Ví dụ: 21,500 hoặc 21.5.",
    "format_unknown": "Không đọc được \"{text}\". Ví dụ: 21500 hoặc 21,5.",
}


def error_detail(code: str, *, message: str | None = None, **fields: Any) -> dict[str, Any]:
    """The detail of an error response; ``fields`` fill the message's {placeholders}."""
    return {"code": code, "message": message or MESSAGES[code].format(**fields)}


def user_error(status_code: int, code: str, *, extra: dict[str, Any] | None = None, message: str | None = None, **fields: Any) -> HTTPException:
    """An HTTPException whose detail is ``error_detail(code)`` plus ``extra``."""
    return HTTPException(status_code=status_code, detail={**error_detail(code, message=message, **fields), **(extra or {})})
