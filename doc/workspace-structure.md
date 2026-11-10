# Thiết kế workspace

## 1. Mục tiêu

Workspace dùng mô hình monorepo nhỏ, ưu tiên ranh giới rõ và tránh nhân đôi logic. Domain/application flow vẫn độc lập framework; runtime hiện có FastAPI/React, JSON adapter local và nền PostgreSQL/Alembic đang được cutover từng bước.

Kiến trúc backend tuân theo ADR hiện tại: một codebase modular monolith, có thể chạy thành tiến trình API và worker riêng khi triển khai. Không tách thành hai codebase có domain model trùng nhau.

## 2. Cây thư mục đã triển khai

```text
.
|-- AGENTS.md
|-- .gitignore
|-- apps/
|   `-- web/
|       |-- public/
|       |-- src/
|       `-- tests/
|-- services/
|   `-- backend/
|       |-- src/report_qa/
|       |   |-- domain/
|       |   |-- application/
|       |   |-- infrastructure/
|       |   `-- worker/
|       |-- migrations/
|       |   `-- versions/
|       `-- tests/
|           |-- unit/
|           |-- integration/
|           `-- contract/
|-- contracts/
|-- infra/
|   |-- compose/
|   |-- postgres/
|   |-- storage/
|   `-- observability/
|-- datasets/
|   |-- manifests/
|   |-- annotations/
|   |-- splits/
|   |-- schemas/
|   `-- private/
|-- tests/
|   |-- fixtures/
|   |-- mock_data/
|   `-- e2e/
|-- scripts/
`-- doc/
    `-- adr/
```

Các `.gitkeep` chỉ giúp Git lưu thư mục rỗng. `datasets/private/.gitignore` ngăn dữ liệu riêng bị đưa vào repository.

## 3. Trách nhiệm và ranh giới

| Vùng | Chứa | Không được chứa |
|---|---|---|
| `apps/web/` | Ứng dụng trình duyệt, tài nguyên tĩnh, test riêng của web | Truy vấn DB, quyết định quyền sở hữu, công thức nghiệp vụ, khóa provider |
| `services/backend/` | API, worker, domain, persistence, adapter và migration trong cùng codebase | Component giao diện, fixture nghiên cứu lớn, cấu hình hạ tầng theo môi trường |
| `contracts/` | Hợp đồng máy đọc được, có version, dùng qua ranh giới thành phần | Logic thực thi hoặc kiểu nội bộ chỉ dùng trong backend |
| `infra/` | Cấu hình chạy cục bộ/triển khai, DB, storage và quan sát hệ thống | Nghiệp vụ sản phẩm hoặc secret thật |
| `datasets/` | Manifest, annotation, split và schema của bộ đánh giá | PDF người dùng, token, PII hoặc dữ liệu riêng trong Git |
| `tests/` | Fixture dùng chung và E2E xuyên thành phần | Unit test thuộc riêng một module backend/web |
| `scripts/` | Công cụ repository, generator và executable specification | Runtime service hoặc logic chỉ được kiểm chứng qua script |
| `doc/` | Source of truth cho yêu cầu, data, API, flow, ADR và delivery | Secret, binary build hoặc tài liệu không còn chủ sở hữu |

### 3.1 Web

- `public/`: tài nguyên tĩnh được phục vụ nguyên trạng.
- `src/`: source của ứng dụng web. Hiện có demo buildless để review data flow; không có framework dependency hay API runtime.
- `tests/`: component/integration test thuộc web. E2E xuyên web-backend đặt ở `tests/e2e/`.
- Web chỉ gửi intent và hiển thị contract từ backend; không tự quyết định authorization, dependency hoặc kết quả tính toán.

### 3.2 Backend

- `src/`: một codebase dùng chung cho API và worker.
- `migrations/versions/`: migration DB tuần tự, bất biến sau khi đã phát hành.
- `tests/unit/`: domain rule, calculator, state transition và validator không cần hạ tầng.
- `tests/integration/`: DB, storage, queue, transaction và provider adapter.
- `tests/contract/`: kiểm chứng HTTP/event payload và tính tương thích contract.

API và worker được tách ở entrypoint/process, không tách domain thành hai bản sao. Worker không được bỏ qua service/domain boundary để cập nhật bảng tùy ý.

### 3.3 Contracts

`contracts/` hiện đã chứa các JSON Schema của executable specification. Khi scaffold, đây là nơi xuất bản schema ổn định cho request, response, event và fixture; code sinh ra từ contract phải đặt trong vùng generated của consumer và không chỉnh tay.

### 3.4 Datasets và test data

- `datasets/manifests/`: provenance, license, checksum và phiên bản dataset.
- `datasets/annotations/`: nhãn chuẩn có thể review; không chứa dữ liệu nhạy cảm.
- `datasets/splits/`: danh sách ID cho dev/final hoặc các split sau này.
- `datasets/schemas/`: schema kiểm tra manifest và annotation.
- `datasets/private/`: vùng local tuyệt đối không commit.
- `tests/fixtures/`: fixture nhỏ, deterministic, dùng chung cho test.
- `tests/mock_data/`: mock data sinh tự động từ executable specification hiện tại.

Không sao chép cùng một dataset sang nhiều vùng. Test chỉ tham chiếu ID/manifest hoặc fixture tối thiểu cần thiết.

## 4. Cấu trúc dự kiến sau khi chốt scaffold

Phần dưới là định hướng module chi tiết hơn, chưa được tạo trong workspace:

```text
apps/web/src/
|-- app/                 # bootstrap, route, provider
|-- features/            # document, chat, evidence, answer
|-- components/          # UI dùng chung, không chứa nghiệp vụ
`-- lib/                 # API client, formatter, utilities

services/backend/src/report_qa/
|-- api/                 # HTTP entrypoint, middleware, request mapping
|-- worker/              # job entrypoint và handlers
|-- modules/
|   |-- identity/
|   |-- documents/
|   |-- extraction/
|   |-- conversations/
|   |-- evidence/
|   |-- answers/
|   `-- jobs/
`-- shared/              # primitive kỹ thuật thật sự dùng chung
```

Mỗi backend module sau này nên có ranh giới `domain`, `application`, `infrastructure` rõ trong chính module nếu độ phức tạp yêu cầu. Không tạo tầng trống chỉ để khớp mẫu kiến trúc.

## 5. Quy tắc đặt file

1. Đặt file gần thành phần sở hữu nhất; chỉ đưa lên vùng dùng chung khi có ít nhất hai consumer thực tế.
2. Logic quyết định nghiệp vụ thuộc backend domain/application, không thuộc route, worker handler, UI hay script.
3. Hợp đồng qua ranh giới phải có schema/version trong `contracts/`; kiểu nội bộ không cần xuất bản.
4. Test đơn vị nằm cạnh codebase sở hữu; test xuyên thành phần nằm ở root `tests/`.
5. Dữ liệu sinh ra phải tái tạo được bằng generator; không sửa tay `tests/mock_data/`.
6. Mọi secret và dữ liệu người dùng chỉ tồn tại ngoài Git; file ví dụ sau này chỉ dùng giá trị giả.
7. Tên thư mục và file dùng `lowercase-kebab-case` cho docs/config chung; package source tuân theo convention của ngôn ngữ đã chốt.

## 6. Những thứ chủ ý chưa tạo

- `package.json`, lockfile hoặc cấu hình bundler frontend (demo `apps/web/` chạy bằng static server và ESM thường).
- `pyproject.toml`, package backend hoặc entrypoint API/worker.
- Dockerfile, Compose manifest và cấu hình triển khai.
- Migration runner và migration SQL thực thi.
- Pipeline CI/CD, environment template và secret mapping.
- FastAPI route, SQLAlchemy model/repository, object-storage adapter và provider adapter.

Các artifact trên chỉ nên được tạo sau khi các quyết định P0 liên quan trong `open-questions.md` được chốt hoặc một issue scaffold xác định rõ stack/version. Chi tiết phần code đã có xem `data-flow-code-skeleton.md`.

## 7. Thứ tự scaffold đề xuất

1. Chốt runtime, package manager, version policy và local service dependencies.
2. Scaffold backend tối thiểu, nối migration baseline và contract validation.
3. Scaffold web tối thiểu, sinh client từ contract đã version.
4. Thêm local infrastructure và health checks.
5. Di chuyển executable specification vào các test layer tương ứng mà vẫn giữ oracle deterministic.
6. Thêm CI gate theo `test-roadmap.md`.

Mỗi bước phải tạo được một lát cắt chạy và kiểm chứng độc lập; không scaffold đồng loạt các module chưa có hành vi.
