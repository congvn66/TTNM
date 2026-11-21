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
`-- docs/
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
| `docs/` | Source of truth cho yêu cầu, data, API, flow, ADR và delivery | Secret, binary build hoặc tài liệu không còn chủ sở hữu |

### 3.1 Web

Frontend dùng React + Vite + PDF.js. Boundary hiện tại trên branch `migration` là:

```text
apps/web/src/
|-- app/
|   |-- App.jsx          # composition root
|   |-- providers.jsx    # provider boundary, hiện là identity provider
|   `-- app.css          # token/layout dùng toàn app
|-- features/
|   |-- workspace/
|   |   `-- WorkspaceScreen.jsx  # state orchestration: session, upload, chat
|   `-- trace/
|       `-- trace.css             # style cho data-flow inspector
`-- main.jsx
```

`WorkspaceScreen.jsx` vẫn là composition lớn ở migration step đầu tiên; các feature `documents`, `pdf-reader`, `chat` và `evidence` sẽ được tách thành component riêng ở bước kế tiếp khi có test component tương ứng. Không tạo thư mục rỗng chỉ để khớp sơ đồ.

- `public/`: tài nguyên tĩnh được phục vụ nguyên trạng.
- `src/`: source React/Vite, PDF.js viewer, API client và UI feature.
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

## 4. Cấu trúc module và hướng tách tiếp

Cây dưới đây phân biệt phần đã triển khai với phần sẽ tách khi có hành vi độc lập. Migration không di chuyển backend hàng loạt để tránh phá import/API; backend hiện giữ layered-first modular monolith.

```text
apps/web/src/
|-- app/                 # bootstrap, provider, global CSS
|-- features/
|   |-- workspace/       # composition/state orchestration hiện tại
|   |-- documents/       # boundary dự kiến cho session/document list
|   |-- pdf-reader/      # boundary dự kiến cho PDF.js và evidence overlay
|   |-- chat/            # boundary dự kiến cho composer/answer renderer
|   |-- evidence/        # boundary dự kiến cho numeric revision drawer
|   `-- trace/           # data-flow audit UI
`-- shared/              # chỉ tạo khi có ít nhất hai consumer

services/backend/src/report_qa/
|-- api/                 # FastAPI entrypoint, HTTP mapping, local storage facade
|-- application/         # extraction, planning, calculation, flow orchestration
|-- domain/              # contracts, models, invariants, errors
|-- infrastructure/      # persistence/provider adapters
`-- worker/              # job entrypoint/handlers
```

Backend không tạo `modules/` rỗng. Khi một domain có lifecycle, repository và test riêng, tách module theo layered boundary (`domain`, `application`, `infrastructure`) thay vì copy domain model giữa API và worker.
## 5. Quy tắc đặt file

1. Đặt file gần thành phần sở hữu nhất; chỉ đưa lên vùng dùng chung khi có ít nhất hai consumer thực tế.
2. Logic quyết định nghiệp vụ thuộc backend domain/application, không thuộc route, worker handler, UI hay script.
3. Hợp đồng qua ranh giới phải có schema/version trong `contracts/`; kiểu nội bộ không cần xuất bản.
4. Test đơn vị nằm cạnh codebase sở hữu; test xuyên thành phần nằm ở root `tests/`.
5. Dữ liệu sinh ra phải tái tạo được bằng generator; không sửa tay `tests/mock_data/`.
6. Mọi secret và dữ liệu người dùng chỉ tồn tại ngoài Git; file ví dụ sau này chỉ dùng giá trị giả.
7. Tên thư mục và file dùng `lowercase-kebab-case` cho docs/config chung; package source tuân theo convention của ngôn ngữ đã chốt.

## 6. Phần chưa tách hoặc chưa bật runtime

- `WorkspaceScreen.jsx` chưa tách hoàn toàn thành các feature component; migration giữ nguyên luồng để giảm rủi ro UI.
- PostgreSQL/Alembic, object storage và provider thật đã có contract/scaffold nhưng runtime chính vẫn dùng JSON local theo `storage-and-data-runtime.md`.
- CI/CD, production auth, queue thật và observability backend đầy đủ chưa phải mục tiêu của migration branch.

Các phần trên chỉ được bật sau khi có contract, migration/test và exit gate tương ứng; không đưa adapter thử nghiệm vào đường chạy chính chỉ để lấp đầy cây thư mục. Chi tiết xem `docs/PLAN/` và `data-flow-code-skeleton.md`.
## 7. Thứ tự scaffold đề xuất

1. Chốt runtime, package manager, version policy và local service dependencies.
2. Scaffold backend tối thiểu, nối migration baseline và contract validation.
3. Scaffold web tối thiểu, sinh client từ contract đã version.
4. Thêm local infrastructure và health checks.
5. Di chuyển executable specification vào các test layer tương ứng mà vẫn giữ oracle deterministic.
6. Thêm CI gate theo `test-roadmap.md`.

Mỗi bước phải tạo được một lát cắt chạy và kiểm chứng độc lập; không scaffold đồng loạt các module chưa có hành vi.
