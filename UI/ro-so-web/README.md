# Rõ Số — Hỏi đáp báo cáo

Giao diện web app bằng Node.js thuần, được tổ chức theo luồng hỏi đáp tài liệu: danh sách PDF gọn ở cạnh trái, trình xem PDF ở vùng chính và hội thoại ở cạnh phải. Bảng số liệu được mở dưới dạng drawer khi người dùng chọn **Bảng số liệu**, để không chiếm chỗ khi đọc tài liệu.

## Chạy ứng dụng

Yêu cầu Node.js 18 trở lên. Project không dùng thư viện ngoài.

```bash
npm start
```

Mở `http://localhost:3000` trong trình duyệt. Trên Windows cũng có thể chạy `start.bat`.

## Thành phần

- `server.js`: máy chủ Node.js, phục vụ giao diện và API hỏi đáp theo các quy tắc mẫu.
- `public/index.html`: cấu trúc giao diện.
- `public/styles.css`: bố cục responsive theo kiểu tài liệu + chat, các nút tương tác và bảng dữ liệu dạng drawer.
- `public/app.js`: điều hướng PDF, câu hỏi mẫu, kiểm tra/sửa số liệu, cập nhật phép tính, lọc và xuất CSV/Markdown.
- `public/sample-report.pdf`: PDF minh họa để mở ứng dụng là có tài liệu sẵn.

## Tương tác hiện có

- Tải PDF từ máy và xem bằng trình đọc PDF của trình duyệt.
- Chuyển trang, phóng to/thu nhỏ và mở PDF trong tab khác.
- Gửi câu hỏi và xem câu trả lời mẫu, cách tính, nguồn có thể nhấp để chuyển tới trang PDF.
- Mở/đóng bảng dữ liệu ở cạnh dưới, sửa giá trị, tính lại tỷ lệ thay đổi, xác nhận dữ liệu, lọc mục cần kiểm tra và xuất CSV.
- Xuất báo cáo kiểm tra dưới dạng Markdown.
- Giao diện tự điều chỉnh ở màn hình nhỏ; trên mobile nội dung PDF nằm phía trên hội thoại.

## Giới hạn hiện tại

Đây là nguyên mẫu tương tác dùng dữ liệu và quy tắc mẫu. Tải PDF mới thay đổi tài liệu đang xem, nhưng chưa tự động trích xuất dữ liệu mới từ PDF. Chưa tích hợp OCR/VLM hoặc mô hình AI hỏi đáp; câu trả lời được xử lý bằng quy tắc trong API Node.js.
