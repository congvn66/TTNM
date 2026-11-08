# Handout cho Tiền — đọc văn bản, bảng và biểu đồ theo nhu cầu

## 1. Kết quả cần bàn giao

Tiền sở hữu adapter biến tài liệu thành evidence có thể kiểm chứng. Output duy nhất qua boundary là [document-evidence-v2.schema.json](../../contracts/document-evidence-v2.schema.json).

Có hai chế độ chạy:

- `base_document`: chạy sau upload, đọc toàn bộ text và bảng; không đọc giá trị từ chart.
- `on_demand_chart`: chỉ chạy sau khi `QuestionPlan.status=ready`, resolver chưa tìm đủ fact bắt buộc và `source_strategy.chart_fact_keys` chứa fact đó.

## 2. Bất biến của mọi con số

Mỗi evidence số phải có đủ:

- `evidence_key`, `source_region_key`, `document_version_id` từ batch;
- `page_number` bắt đầu từ 1;
- `bbox=[x0,y0,x1,y1]` chuẩn hóa 0..1, gốc trên-trái, bao đúng nhãn/ô chứa số;
- `numeric_value` là chuỗi thập phân, không phải float;
- `raw_text` giữ nội dung nhìn thấy để audit;
- `measure`, `subject`, `period`, `unit`, `dimensions`;
- `data_status`, `extraction_method`, `method_label`, `confidence`.

Không được trả `bbox=null` cho evidence số. Nếu không xác định được vị trí thì evidence không đạt contract và phải trở thành warning/error, không được đưa vào calculator.

## 3. Văn bản

Với số trong đoạn văn:

- `source_type=text`;
- `extraction_method=text`;
- `method_label="đọc từ văn bản"`;
- bbox bao đúng cụm số và đơn vị; nếu engine chỉ có bbox dòng thì lưu bbox dòng và đánh confidence thấp hơn;
- period chỉ được gán khi có căn cứ trong câu, heading hoặc vùng liên kết. Không lấy năm upload làm kỳ số liệu.

Ví dụ:

```json
{
  "evidence_key": "ev-revenue-q1",
  "source_region_key": "page-2-line-14",
  "source_type": "text",
  "page_number": 2,
  "bbox": [0.18, 0.31, 0.42, 0.34],
  "raw_text": "Doanh thu Q1/2026 đạt 2.785 tỷ đồng",
  "numeric_value": "2785",
  "data_status": "valid",
  "extraction_method": "text",
  "method_label": "đọc từ văn bản",
  "semantic": {
    "measure": "doanh_thu",
    "subject": null,
    "period": {"label": "Q1/2026", "start": "2026-01-01", "end": "2026-03-31", "granularity": "quarter"},
    "unit": "VND_BILLION",
    "dimensions": {}
  },
  "table_locator": null,
  "chart_read": null,
  "confidence": 0.98
}
```

## 4. Bảng

Mỗi ô số là một evidence độc lập:

- `source_type=table`, `extraction_method=table_cell`, `method_label="đọc từ ô bảng"`;
- bbox bao ô số, không bao cả bảng;
- `table_locator` chứa row/column index và header đã resolve;
- unit lấy từ cell, header cột, header bảng hoặc footnote theo thứ tự gần nhất có căn cứ;
- merged cells phải được trải quan hệ header, không nhân bản thành nhiều số;
- dấu `-` phải phân biệt zero, missing và số âm dựa trên quy ước bảng/footnote.

Kiểm tra bắt buộc:

- cùng một cell không sinh hai evidence số trùng nhau;
- đổi thứ tự OCR không làm mất quan hệ header;
- số trong footnote không bị hiểu là giá trị của hàng dữ liệu;
- bbox của cell nằm trong bbox của table region.

### PDF scan và OCR

- OCR chỉ chạy khi trang không có text layer; PDF số không được OCR lại.
- Adapter chuẩn là PyMuPDF + Tesseract; mỗi token OCR phải có `bbox` chuẩn hóa và `confidence`.
- Evidence OCR dùng `source_type=text`, `extraction_method=ocr`, `method_label="đọc bằng OCR"`.
- Nếu thiếu dependency hoặc binary Tesseract, trả warning `OCR_PYTHON_DEPENDENCY_MISSING` hoặc `TESSERACT_ENGINE_UNAVAILABLE`; không được coi trang rỗng là đã đọc xong.
- Bảng phức tạp dùng adapter pdfplumber. Header nhiều hàng/merged cell trả `column_header` theo đường dẫn header; mỗi ô vật lý chỉ sinh một evidence.

## 5. Biểu đồ — chỉ đọc khi câu hỏi cần

Không quét và số hóa mọi chart lúc upload. Luồng đúng:

1. Nhận `question_plan_id`, `fact_keys`, `chart_region_keys` trong `trigger`.
2. Chỉ mở đúng trang/chart được chỉ định.
3. Chỉ tìm series/category/period cần cho các fact đó.
4. Trả evidence chart và kết thúc; không tự tính tổng, hiệu hoặc phần trăm.

Mỗi số chart bắt buộc ghi một trong hai nhãn:

- `direct_label` + **“đọc từ nhãn”**: số được in trực tiếp cạnh điểm/cột/lát biểu đồ.
- `axis_estimation` + **“ước lượng theo trục”**: không có nhãn trực tiếp; giá trị được nội suy theo vị trí và tick trục.

Với `axis_estimation`, `chart_read` phải ghi `axis_label`, `axis_unit`, `lower_tick`, `upper_tick` và assumptions. Không ước lượng khi:

- không xác định được scale tuyến tính/log;
- tick hoặc đơn vị bị cắt;
- series/category không phân biệt được;
- error bar, stacked bar hoặc dual axis gây hai cách hiểu;
- độ tin cậy thấp hơn ngưỡng được cấu hình.

Các trường hợp đó trả `data_status=ambiguous|unreadable`, không trả một con số đoán.

## 6. Quy tắc chuẩn hóa

- Giữ `raw_text` nguyên bản; chuẩn hóa số vào `numeric_value`.
- Dấu phân cách Việt Nam: `2.785,4` có thể thành `2785.4` chỉ khi locale được xác định.
- Ký hiệu `%` dùng unit `PERCENT`; không tự đổi `12%` thành `0.12` tại extraction boundary.
- Tiền tệ và hệ số nghìn/triệu/tỷ phải thể hiện trong unit chuẩn.
- Không làm tròn giá trị gốc. Với ước lượng chart, độ chính xác phải tương ứng khoảng cách tick, không tạo thêm chữ số giả.

## 7. Failure contract

| Tình huống | Output |
|---|---|
| số không đọc được | `data_status=unreadable`, `numeric_value=null`, warning |
| thiếu period/unit | evidence vẫn có thể tồn tại nhưng field là null; resolver không dùng nếu fact yêu cầu field đó |
| hai cách gán series | `data_status=ambiguous`, không chọn ngẫu nhiên |
| chart không nằm trong trigger | không đọc, warning `CHART_OUT_OF_SCOPE` nếu provider trả dư |
| bbox ngoài 0..1 hoặc đảo tọa độ | reject toàn batch |
| provider timeout | job retry có giới hạn; không publish batch dở dang |

## 8. Acceptance tests tối thiểu

1. Text: số + unit + kỳ + bbox đúng trên một trang.
2. Bảng: số resolve đúng row header/column header và bbox cell.
3. Bảng merged header và footnote.
4. Chart có nhãn: method là `direct_label`/“đọc từ nhãn”.
5. Chart không nhãn: method là `axis_estimation`/“ước lượng theo trục”, có hai tick.
6. Chart không cần thiết: assert adapter chart không được gọi.
7. Chart mơ hồ/dual-axis: không sinh giá trị valid.
8. Locale Việt Nam, số 0, số âm, missing và `%`.
9. Mọi payload validate schema; payload thiếu page/bbox phải fail.

## 9. Không thuộc trách nhiệm của Tiền

- Không quyết định người dùng muốn phép tính nào.
- Không hỏi lại người dùng.
- Không cộng/trừ/tính phần trăm.
- Không viết câu trả lời cuối.
- Không sửa evidence đã publish; correction tạo revision ở domain layer.
