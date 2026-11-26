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
    "REQUEST_INVALID": "Yêu cầu không hợp lệ; hãy kiểm tra lại dữ liệu đã nhập.",
    "NOT_FOUND": "Không tìm thấy địa chỉ này.",
    "METHOD_NOT_ALLOWED": "Thao tác này không được hỗ trợ ở địa chỉ này.",
    "HTTP_ERROR": "Máy chủ không xử lý được yêu cầu này.",
    "INTERNAL_ERROR": "Máy chủ gặp lỗi khi xử lý yêu cầu. Hãy thử lại sau.",
    "INVALID_IDEMPOTENCY_KEY": "Idempotency-Key quá dài.",
    "IDEMPOTENCY_KEY_REUSED": "Idempotency-Key đã được dùng cho một câu hỏi khác.",
    # Sessions and documents
    "SESSION_NOT_FOUND": "Không tìm thấy phiên làm việc.",
    "SESSION_TITLE_REQUIRED": "Hãy nhập tên phiên làm việc.",
    "DOCUMENT_NOT_FOUND": "Không tìm thấy tài liệu.",
    "DOCUMENT_NAME_INVALID": "Tên tài liệu không hợp lệ.",
    "DOCUMENT_FILE_MISSING": "Không tìm thấy tệp PDF đã lưu của tài liệu này.",
    "MESSAGE_TRACE_NOT_FOUND": "Không tìm thấy nhật ký xử lý của câu trả lời này.",
    # Uploads
    "UPLOAD_FORM_INVALID": "Không đọc được tệp tải lên. Tên tệp có thể quá dài; hãy đổi tên tệp ngắn hơn (tối đa 255 ký tự) rồi tải lên lại.",
    "PDF_REQUIRED": "Chỉ chấp nhận tệp .pdf.",
    "INVALID_PDF": "Không đọc được tệp này như một PDF hợp lệ.",
    "EMPTY_PDF": "Tệp PDF rỗng.",
    "PDF_TOO_LARGE": "Kích thước PDF tối đa là {max_mib} MiB.",
    "PDF_TOO_MANY_PAGES": "PDF vượt quá giới hạn {max_pages} trang.",
    "PDF_ENCRYPTED": "PDF này được đặt mật khẩu nên không đọc được. Hãy gỡ mật khẩu rồi tải lên lại.",
    "OBJECT_STORAGE_UNAVAILABLE": "Cloudflare R2 tạm thời không sẵn sàng; hãy thử lại sau.",
    # Extraction
    "EXTRACTION_NOT_READY": "Tài liệu chưa đọc xong hoặc đang được đọc lại. Hãy thử lại khi tài liệu sẵn sàng.",
    "EXTRACTION_IN_PROGRESS": "Tài liệu đang được đọc.",
    "EXTRACTION_UPGRADE_FAILED": "Không nâng cấp được kết quả đọc cũ của tài liệu; hãy đọc lại tài liệu.",
    "REEXTRACTION_NOT_SUPPORTED": "Chưa hỗ trợ đọc lại tài liệu khi lưu bằng PostgreSQL; hãy tải lại PDF.",
    # Numbers
    "EVIDENCE_NOT_FOUND": "Không tìm thấy số liệu trong tài liệu.",
    "EVIDENCE_REVISION_CONFLICT": "Số liệu đã được sửa bởi thao tác khác; hãy tải lại lịch sử trước khi sửa tiếp.",
    "VALUE_UNCHANGED": "Giá trị mới trùng giá trị hiện tại; không có gì để lưu.",
    "INVALID_DECIMAL": "Không đọc được số từ giá trị đã nhập.",
    "NUMBER_FORMAT_AMBIGUOUS": "Không rõ dấu phân cách trong \"{text}\" là hàng nghìn hay thập phân. Hãy nhập số không có dấu phân cách hàng nghìn, ví dụ 21500 hoặc 21,5.",
    # Answers
    "NO_TEXT_EVIDENCE": "Không tìm thấy đoạn văn bản đủ liên quan để trả lời; hãy hỏi bằng thuật ngữ có trong tài liệu.",
    "CHART_EVIDENCE_PERSISTENCE_FAILED": "Không lưu được số liệu đọc từ biểu đồ; hãy thử lại câu hỏi.",
    "AI_PROVIDER_UNAVAILABLE": "Không kết nối được tới dịch vụ AI. Kiểm tra mạng hoặc thử lại sau.",
    "AI_PROVIDER_TIMEOUT": "Dịch vụ AI phản hồi quá lâu. Bạn có thể thử lại câu hỏi.",
    "AI_MODEL_UNAVAILABLE": "Mô hình AI hiện không khả dụng. Kiểm tra lại cấu hình model.",
    "AI_PROVIDER_HTTP_ERROR": "Dịch vụ AI từ chối yêu cầu. Kiểm tra API key và giới hạn sử dụng.",
    "AI_NOT_CONFIGURED": "Chưa cấu hình nhà cung cấp AI cho môi trường này.",
    "AI_INVALID_OUTPUT": "AI trả về dữ liệu không đúng định dạng. Hãy thử lại câu hỏi.",
    "AI_UNGROUNDED_CITATION": "AI trả về trích dẫn không nằm trong tài liệu. Hãy thử lại câu hỏi.",
    "AI_UNSUPPORTED_EVIDENCE": "AI chưa xác minh được evidence trong tài liệu. Hãy thử lại câu hỏi.",
    "DOCUMENT_CONTEXT_TOO_LARGE": "Tài liệu quá dài để trợ lý đọc hết trong một lần hỏi.",
    "ASSISTANT_INCOMPLETE": "Trợ lý chưa hoàn tất câu trả lời trong số bước cho phép. Hãy thử lại hoặc hỏi cụ thể hơn.",
    "AI_PROVIDER_BAD_RESPONSE": "Dịch vụ AI trả về phản hồi không hợp lệ. Hãy thử lại sau.",
    "AI_ANSWER_TIMEOUT": "Trợ lý chưa trả lời xong trong thời gian cho phép. Hãy thử lại hoặc hỏi cụ thể hơn.",
    "AI_FAILED": "Không thể tạo câu trả lời. Hãy thử lại.",
    # Durable jobs
    "DURABLE_QUEUE_DISABLED": "Hàng đợi xử lý bền vững cần PostgreSQL.",
    "QUEUE_UNAVAILABLE": "Hàng đợi xử lý chưa sẵn sàng. Hãy khởi động worker hoặc thử lại sau.",
    "JOB_NOT_FOUND": "Không tìm thấy tác vụ.",
    "JOB_NOT_CANCELLABLE": "Chỉ hủy được tác vụ đang chờ hoặc đang chạy.",
    "JOB_NOT_RETRYABLE": "Chỉ chạy lại được tác vụ đã lỗi.",
    # Library
    "LIBRARY_REQUIRES_POSTGRES": "Thư viện tài liệu cần PostgreSQL.",
    "PROJECT_NOT_FOUND": "Không tìm thấy thư viện này.",
    "PROJECT_NAME_CONFLICT": "Tên thư viện đã tồn tại.",
    "PROJECT_NOT_EMPTY": "Hãy chuyển hoặc lưu trữ các phiên trước khi xóa thư viện.",
    "PROJECT_DOCUMENT_NOT_FOUND": "Tài liệu không nằm trong thư viện này.",
    "PROJECT_DOCUMENT_REVISION_CONFLICT": "Tài liệu vừa được thay đổi; hãy tải lại.",
    "INVALID_FOLDER_PARENT": "Thư mục cha không thuộc thư viện này.",
    "FOLDER_NAME_CONFLICT": "Tên thư mục đã tồn tại.",
    "FOLDER_NOT_FOUND": "Không tìm thấy thư mục.",
    "FOLDER_REVISION_CONFLICT": "Thư mục vừa được thay đổi; hãy tải lại trước khi sửa.",
    "FOLDER_CYCLE": "Không thể đặt một thư mục vào chính nó.",
    # Accounts
    "AUTH_REQUIRES_POSTGRES": "Đăng nhập cần PostgreSQL để lưu phiên đăng nhập bền vững.",
    "INVALID_EMAIL": "Email không hợp lệ.",
    "CSRF_ORIGIN_REJECTED": "Origin không được phép.",
    "AUTH_REQUIRED": "Vui lòng đăng nhập.",
    "EMAIL_ALREADY_REGISTERED": "Không thể tạo tài khoản với thông tin này.",
    "INVALID_CREDENTIALS": "Email hoặc mật khẩu không đúng.",
    "RESET_TOKEN_INVALID": "Liên kết đặt lại không hợp lệ hoặc đã hết hạn.",
    "PASSWORD_UNCHANGED": "Mật khẩu mới phải khác mật khẩu hiện tại.",
    "CURRENT_PASSWORD_INVALID": "Mật khẩu hiện tại không đúng.",
    "AUTH_SESSION_NOT_FOUND": "Không tìm thấy phiên đăng nhập.",
    "AUTH_DATABASE_UNAVAILABLE": "Không thể kết nối dữ liệu tài khoản lúc này. Hãy thử lại sau.",
}

# Why a typed number was refused; each is sent as the message of INVALID_DECIMAL.
NUMBER_INPUT_MESSAGES = {
    "empty": "Hãy nhập một số.",
    "exponent": "Không dùng dạng số mũ (ví dụ 1e5); hãy nhập đủ các chữ số.",
    "percent": "Số liệu này không phải tỷ lệ phần trăm; hãy nhập số không có dấu %.",
    "too_many_digits": "Số có quá nhiều chữ số; tối đa {limit} chữ số có nghĩa.",
    "not_exact": "Giá trị phải là chuỗi thập phân chính xác, ví dụ 58 hoặc 58.25.",
    "format_vi": "Không đọc được \"{text}\" thành một số: tài liệu này dùng dấu chấm ngăn hàng nghìn và dấu phẩy thập phân. Ví dụ hợp lệ: 21.500 hoặc 21,5.",
    "format_en": "Không đọc được \"{text}\" thành một số: tài liệu này dùng dấu phẩy ngăn hàng nghìn và dấu chấm thập phân. Ví dụ hợp lệ: 21,500 hoặc 21.5.",
    "format_unknown": "Không đọc được \"{text}\" thành một số: mỗi nhóm sau dấu ngăn hàng nghìn phải có đúng 3 chữ số và chỉ có một dấu thập phân. Ví dụ hợp lệ: 21500 hoặc 21,5.",
}


def error_detail(code: str, *, message: str | None = None, **fields: Any) -> dict[str, Any]:
    """The detail of an error response; ``fields`` fill the message's {placeholders}."""
    return {"code": code, "message": message or MESSAGES[code].format(**fields)}


def user_error(status_code: int, code: str, *, extra: dict[str, Any] | None = None, message: str | None = None, **fields: Any) -> HTTPException:
    """An HTTPException whose detail is ``error_detail(code)`` plus ``extra``."""
    return HTTPException(status_code=status_code, detail={**error_detail(code, message=message, **fields), **(extra or {})})
