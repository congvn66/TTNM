# Kế hoạch kiến trúc frontend production

> Trạng thái: Proposed - chờ duyệt. Tài liệu này không yêu cầu rewrite ngay toàn bộ UI.

## 1. Vấn đề hiện tại

`App.jsx` không phải vấn đề chính. `WorkspaceScreen.jsx` mới là điểm gộp quá mức vì đang giữ:

- page layout và responsive shell;
- fetch/mutation tới nhiều endpoint;
- session/document selection;
- PDF rendering, zoom, pagination và evidence overlay;
- chat, structured answer, optimistic message;
- audit/evidence drawer;
- loading/error/job state.

Hệ quả: một thay đổi nhỏ có thể làm hỏng PDF, chat hoặc layout; component khó test độc lập; request state và UI state trộn nhau.

## 2. Nguyên tắc tổ chức

- Tách theo **feature và use case**, không tách tùy ý theo kích thước file.
- Page chỉ compose feature; feature không import ngược page.
- Server state dùng TanStack Query; transient UI state dùng React state/context cục bộ.
- Shared chỉ chứa thành phần thật sự dùng lại từ hai feature trở lên.
- API response được parse/validate ở boundary; component không đọc raw response tùy tiện.
- Migrate JSX sang TSX theo feature, không big-bang rewrite.

## 3. Tree đích

```text
apps/web/src/
├── app/
│   ├── App.tsx
│   ├── router.tsx
│   ├── providers.tsx
│   ├── ErrorBoundary.tsx
│   └── styles/
│       ├── tokens.css
│       ├── themes.css
│       └── globals.css
├── pages/
│   ├── LoginPage/
│   ├── LibraryPage/
│   ├── WorkspacePage/
│   ├── SettingsPage/
│   └── NotFoundPage/
├── features/
│   ├── auth/
│   ├── library/
│   ├── document-upload/
│   ├── document-actions/
│   ├── processing-jobs/
│   ├── pdf-reader/
│   ├── chat/
│   ├── evidence/
│   └── settings/
├── entities/
│   ├── user/
│   ├── project/
│   ├── folder/
│   ├── document/
│   ├── document-version/
│   └── job/
├── shared/
│   ├── api/
│   │   ├── client.ts
│   │   ├── errors.ts
│   │   ├── queryKeys.ts
│   │   └── generated/
│   ├── ui/
│   ├── hooks/
│   ├── lib/
│   ├── assets/
│   └── types/
└── main.tsx
```

Mỗi feature có thể có `api/`, `model/`, `ui/`, `lib/` và `tests/`. Không bắt buộc tạo đủ các thư mục rỗng.

## 4. Route và page shell

| Route | Chức năng |
|---|---|
| `/login`, `/register`, `/forgot-password` | Auth flow |
| `/app` | Redirect tới project/library gần nhất |
| `/app/library/:projectId` | Folder tree, document list/grid, upload và bulk action |
| `/app/workspace/:documentId` | PDF reader + chat + citations + job state |
| `/app/settings/profile` | Hồ sơ |
| `/app/settings/preferences` | Theme, language, AI preference |
| `/app/settings/security` | Password, sessions |

`AuthenticatedShell` chứa sidebar điều hướng, account menu và global upload/job center. `WorkspacePage` có shell riêng tối ưu không gian đọc, nhưng vẫn dùng cùng navigation primitives.

## 5. Component boundaries cho workspace

```text
WorkspacePage
├── WorkspaceHeader
├── DocumentReaderPanel
│   ├── PdfToolbar
│   ├── PdfViewport
│   ├── EvidenceLayer
│   └── PageNavigator
├── ConversationPanel
│   ├── ConversationHeader
│   ├── MessageList
│   │   ├── UserMessage
│   │   ├── AssistantMessage
│   │   └── AnswerBlocks
│   ├── JobMessageState
│   └── Composer
└── CitationInspector (contextual, không phải audit drawer)
```

Rules:

- `PdfViewport` chỉ nhận document URL/page/scale và normalized evidence; không gọi chat API.
- `EvidenceLayer` dùng normalized coordinates `[0,1]`, không biết DOM chat.
- `Composer` tạo user message optimistic ngay khi Enter, cuộn xuống sau khi append và không chờ model.
- `JobMessageState` hiển thị queued/running/retrying/failed/cancelled; không giả lập câu trả lời offline.
- `AssistantMessage` render structured blocks: paragraph, heading, list, table, formula, citation và warning.
- Audit raw request/response bị gỡ khỏi product route.

## 6. Server state và API client

- Dùng một `ApiClient` có base URL tương đối `/api`, cookie credentials, timeout và normalized error.
- OpenAPI sinh request/response types; schema quan trọng vẫn parse runtime bằng Zod hoặc validator tương đương.
- Query key có factory ổn định: `documents.detail(id)`, `jobs.detail(id)`.
- Mutation cập nhật cache bằng server response; không tự chế object khác contract.
- Retry chỉ cho lỗi network/5xx an toàn; mutation không retry nếu thiếu idempotency key.
- Auth 401 đi qua một handler tập trung; không redirect vòng lặp.

Không thêm Redux ở giai đoạn này. Chỉ xem xét khi state cross-feature phức tạp không giải quyết được bằng query cache và scoped context.

## 7. Design system

Hướng thẩm mỹ: B2B document intelligence, tin cậy, rõ ràng, không dùng gradient tím/hồng hoặc robot AI đại trà.

### Tokens nền

```css
:root {
  --color-brand-900: #0f172a;
  --color-brand-700: #334155;
  --color-action-600: #0369a1;
  --color-surface: #f8fafc;
  --color-text: #020617;
  --radius-control: 10px;
  --radius-panel: 14px;
  --font-sans: "Plus Jakarta Sans", system-ui, sans-serif;
}
```

Dark theme phải là bộ token semantic riêng, không dùng `filter` hoặc đảo màu PDF. PDF canvas giữ màu gốc; chrome và panel đổi theme.

### Primitives bắt buộc

`Button`, `IconButton`, `Input`, `Textarea`, `Select`, `Checkbox`, `Menu`, `Dialog`, `Drawer`, `Tooltip`, `Tabs`, `Toast`, `Badge`, `Progress`, `Skeleton`, `EmptyState`, `ErrorState`, `FileThumbnail`, `JobStatus`.

Mỗi primitive có variant, size, loading, disabled, focus-visible và test accessibility.

## 8. Theme và preference

- Ba lựa chọn: `light`, `dark`, `system`.
- Trước login: lưu local preference và áp dụng trước khi React mount để tránh flash.
- Sau login: DB là source of truth, local cache dùng để bootstrap.
- Khi `system`, lắng nghe `prefers-color-scheme`.
- `color-scheme` khai báo đúng để control native đồng bộ.
- Không lưu theme trong nhiều context/feature khác nhau.

## 9. Library UX

- Sidebar: project switcher và folder tree.
- Main: breadcrumb, search, sort, filter, list/grid toggle.
- Toolbar theo selection: move, archive, restore, delete.
- Context menu và keyboard đều gọi cùng command handler.
- Upload tray hiển thị từng file: hashing, uploading, queued, extracting, ready, failed.
- Rename inline có validation và rollback khi server từ chối.
- Destructive action dùng confirmation mô tả hậu quả; undo cho archive/move khi khả thi.

## 10. Loading, error và recovery

- Page-level skeleton chỉ cho first load; refresh giữ content cũ và hiển thị subtle progress.
- Empty state khác với no-search-result và permission error.
- Error có correlation ID, retry phù hợp và hành động quay lại an toàn.
- AI job failed không xóa user message; assistant slot giữ thứ tự và cho retry.
- `aria-live` thông báo upload/job/error nhưng không lặp thông báo gây nhiễu.
- ErrorBoundary ở app và route; PDF/Chat có boundary riêng để một panel lỗi không làm trắng toàn trang.

## 11. Responsive và accessibility

- Desktop >= 1280: library sidebar + content; workspace reader/chat split resizable.
- Tablet: sidebar collapsible, workspace chuyển tab reader/chat.
- Mobile: ưu tiên library và chat; PDF mở trình đọc toàn màn hình.
- Target chạm tối thiểu 44x44; visible focus; logical tab order.
- Dialog trap focus và trả focus về trigger.
- Không dùng màu đơn thuần để biểu thị trạng thái.
- Tôn trọng `prefers-reduced-motion`.

## 12. Kế hoạch migration frontend

1. FE-001: thêm router/providers/error boundary và giữ workspace cũ trong một route.
2. FE-002: tạo shared API client + query layer; thay fetch rải rác.
3. FE-003: tách `PdfViewer` và evidence feature, thêm component tests.
4. FE-004: tách chat/messages/composer/job state.
5. FE-005: tạo authenticated shell, library và settings routes.
6. FE-006: theme tokens và primitives.
7. FE-007: xóa audit trace feature khỏi product bundle.
8. FE-008: migrate feature đã ổn định sang TSX.

Mỗi bước phải build được và giữ E2E smoke pass; không tạo branch kéo dài nhiều tuần.

## 13. Definition of Done

- `WorkspaceScreen.jsx` không còn component đa trách nhiệm; page chỉ compose feature.
- Không có raw `fetch` ngoài shared API/feature API modules.
- Không có audit/debug drawer ở build production.
- Light/dark/system không flash theme và hoạt động ở mọi route.
- Upload/chat/job có loading, retry, cancel và failure state đúng.
- PDF/citation scale invariant qua zoom, resize và fullscreen.
- Keyboard, focus, contrast và responsive QA pass.
- Bundle routes lazy-load; PDF engine không nằm trong initial chunk của login/library nếu chưa cần.
