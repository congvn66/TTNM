# Kế hoạch Library, file, folder và PDF version

> Trạng thái: Proposed - chờ duyệt.

## 1. Semantics cần chốt trước UI

- `project` là workspace cấp cao của một owner.
- `folder` là cây phân cấp bên trong một project.
- Một document có thể được liên kết vào project; vị trí folder và display name thuộc liên kết đó.
- File PDF gốc và extraction đã publish là immutable.
- Rename chỉ đổi `display_name`, không đổi object key hay bytes.
- "Sửa/thay PDF" là upload binary mới tạo `document_version` mới, sau đó chạy extraction mới.
- Archive là thao tác phục hồi được; purge là job bất đồng bộ sau retention và dependency check.
- Xóa khỏi project gỡ association, không mặc định xóa document đang được tham chiếu nơi khác.

Nếu không chốt các nghĩa này, UI "xóa/sửa PDF" dễ gây mất dữ liệu hoặc làm citation cũ trỏ sai.

## 2. Data model đề xuất

### `folders`

```text
id uuid PK
owner_id uuid FK
project_id uuid FK
parent_id uuid NULL FK folders
name text NOT NULL
normalized_name text NOT NULL
sort_order numeric NOT NULL DEFAULT 0
created_at, updated_at timestamptz
deleted_at timestamptz NULL
version bigint NOT NULL
UNIQUE(project_id, parent_id, normalized_name) WHERE deleted_at IS NULL
```

Application và DB trigger/constraint phù hợp phải ngăn self-parent và cycle. Root không cần một row giả; `parent_id = NULL` là root project.

### Mở rộng `project_documents`

```text
project_id uuid
document_id uuid
owner_id uuid
folder_id uuid NULL
display_name text NOT NULL
sort_order numeric NOT NULL DEFAULT 0
added_at, updated_at timestamptz
archived_at timestamptz NULL
version bigint NOT NULL
PRIMARY KEY(project_id, document_id)
```

`folder_id` phải thuộc cùng owner/project. `display_name` có thể trùng nếu product cho phép; nếu không, dùng unique normalized name cùng folder. Đề xuất phiên bản đầu: không cho trùng tên trong cùng folder để UX rõ ràng.

### `documents`

Giữ identity logic, checksum/dedup policy và current version pointer. Không lưu absolute local path.

### `document_versions`

```text
id uuid PK
document_id uuid FK
version_number int
source_filename text
media_type text
size_bytes bigint
sha256 text
object_key text UNIQUE
status text CHECK uploading|queued|processing|ready|failed|archived
created_by uuid
created_at timestamptz
UNIQUE(document_id, version_number)
```

Derived extraction/evidence/chat phải snapshot `document_version_id`, không chỉ `document_id`.

## 3. Object storage layout

```text
owners/{owner_id}/documents/{document_id}/versions/{version_id}/original.pdf
owners/{owner_id}/documents/{document_id}/versions/{version_id}/artifacts/pages/{page}.png
owners/{owner_id}/documents/{document_id}/versions/{version_id}/artifacts/extraction.json
```

- Bucket private; browser dùng presigned URL thời hạn ngắn.
- API không trả object key nội bộ như public URL.
- Upload có size/media/checksum validation.
- Hoàn tất upload chỉ khi object tồn tại và checksum khớp.
- Cleanup orphan multipart/object chạy bằng scheduled job.

## 4. Command semantics

### Create folder

- Validate parent cùng project/owner.
- Normalize name; reject reserved/empty/duplicate.
- Transaction insert + audit operational log.

### Rename folder/document

- Nhận `expected_version` hoặc `If-Match` để chống lost update.
- Rename document chỉ sửa association display name.
- Trả resource mới từ server; UI cập nhật theo response.

### Move

- Folder move phải ngăn chuyển vào chính descendant.
- Document move chỉ đổi `folder_id` trong cùng project.
- Cross-project move giai đoạn đầu là copy association rồi remove source trong một transaction; phải xác nhận semantics trước khi expose.

### Replace PDF

1. Tạo pending `document_version` và upload intent.
2. Upload object, complete với checksum/idempotency key.
3. Enqueue extraction job cho version mới.
4. Chỉ đổi `current_version_id` khi extraction publish thành công hoặc theo policy user-confirmed.
5. Chat/citation cũ vẫn gắn version cũ và không bị silently rebase.

### Archive, restore, purge

- Archive association ngay, có undo/restore.
- Purge chỉ khi retention hết, không còn association/dependency hợp lệ và user đã xác nhận.
- Purge là durable job: xóa derived artifacts trước, original sau, metadata cuối; ghi tombstone/result.
- Failure giữa chừng phải retry idempotent.

## 5. API contract đề xuất

| Method | Endpoint | Mục đích |
|---|---|---|
| GET/POST | `/api/v1/projects` | list/create project |
| GET/PATCH/DELETE | `/api/v1/projects/{project_id}` | detail/rename/archive |
| GET/POST | `/api/v1/projects/{project_id}/folders` | tree/create folder |
| PATCH/DELETE | `/api/v1/folders/{folder_id}` | rename/move/archive |
| GET | `/api/v1/projects/{project_id}/documents` | paginated search/sort/filter |
| POST | `/api/v1/projects/{project_id}/documents/uploads` | create upload intent |
| POST | `/api/v1/uploads/{upload_id}/complete` | verify và enqueue extraction |
| PATCH | `/api/v1/project-documents/{document_id}` | rename/move/archive association |
| POST | `/api/v1/documents/{document_id}/versions` | replace bằng version mới |
| GET | `/api/v1/documents/{document_id}/versions` | version history |
| POST | `/api/v1/project-documents/bulk` | bulk move/archive/restore |
| DELETE | `/api/v1/documents/{document_id}` | request purge nếu đủ điều kiện |

List dùng cursor pagination; search/sort/filter là query server-side. Bulk command trả per-item result nếu có partial failure policy; mặc định ưu tiên all-or-nothing cho move trong cùng project.

## 6. UI Library

```text
LibraryPage
├── ProjectSwitcher
├── FolderTree
├── LibraryToolbar
│   ├── Breadcrumb
│   ├── Search
│   ├── Sort/Filter
│   └── New folder / Upload
├── DocumentCollection (list hoặc grid)
├── SelectionToolbar
├── ContextMenu
├── UploadTray
└── JobCenter
```

Các action phải xuất hiện nhất quán ở context menu, overflow menu và keyboard. Drag-drop chỉ là shortcut; luôn có Move dialog để accessibility và mobile dùng được.

### Trạng thái item

- Uploading: progress byte nếu có.
- Queued: đã bền trong DB, chờ worker.
- Processing: step hiện tại + elapsed, không hiển thị phần trăm giả.
- Ready: mở workspace.
- Failed: lỗi thân thiện + retry/details có correlation ID.
- Archived: chỉ hiện trong filter archive, cho restore/purge.

## 7. Conflict và concurrency

- Rename/move dùng resource version; 409 trả current representation.
- Complete upload idempotent theo key + checksum.
- Double click upload không tạo hai version nếu cùng intent.
- Worker publish kiểm tra `input_data_revision` và version hiện hành.
- Folder tree cache invalidate theo project, không refetch toàn app.

## 8. Task breakdown

1. LIB-001: migration folders + project document metadata/version.
2. LIB-002: repository/commands và cycle/concurrency guards.
3. LIB-003: object-storage upload intent/complete flow.
4. LIB-004: version replacement + extraction job integration.
5. LIB-005: archive/restore/purge workflow.
6. LIB-006: list/search/sort/filter/pagination API.
7. LIB-007: Library page, tree, breadcrumb và item actions.
8. LIB-008: upload tray/job center và bulk actions.
9. LIB-009: migration từ session/local JSON nếu dữ liệu cần giữ.
10. LIB-010: integration/E2E/concurrency tests.

## 9. Test bắt buộc

- Folder duplicate normalized name, illegal parent, deep tree và cycle.
- User A không move/rename/delete resource của user B.
- Rename conflict trả 409, không lost update.
- Replace tạo version mới; bytes/checksum/version cũ không đổi.
- Citation/chat cũ vẫn đọc đúng old `document_version_id`.
- Upload retry/complete duplicate không tạo bản ghi thừa.
- Archive/restore giữ metadata; purge đang được tham chiếu bị chặn.
- Kill worker giữa purge/extraction và retry không làm trạng thái hỏng.
- Presigned URL hết hạn và không public cross-owner.
- Tree/list UI giữ selection/breadcrumb hợp lệ sau move/delete.

## 10. Definition of Done

- Người dùng tạo/đổi tên/di chuyển/archive/restore folder và PDF được từ UI.
- Replace PDF tạo version mới và có version history rõ ràng.
- Không chỉnh sửa hoặc ghi đè original object.
- Mọi thao tác bền qua restart, có ownership check và concurrency guard.
- Upload/extraction/purge chạy qua durable jobs, có retry/cancel phù hợp.
- UI không hứa thao tác đã xong khi server mới chỉ enqueue; trạng thái phản ánh đúng backend.

