# Kế hoạch visual system và custom image assets

> Trạng thái: Proposed - chờ duyệt art direction trước khi generate asset.

## 1. Mục tiêu

Tạo cảm giác sản phẩm B2B document intelligence có bản sắc riêng, không giống dashboard template hoặc giao diện AI tím-gradient đại trà. Asset phải hỗ trợ hiểu trạng thái, không trang trí lấn át PDF và dữ liệu.

## 2. Phản biện yêu cầu PNG icon

Không nên dùng PNG cho functional icon như Upload, Rename, Delete, Settings, Zoom:

- mờ ở nhiều DPI/zoom;
- khó đổi màu theo theme/state;
- nặng và khó accessibility;
- khó giữ stroke/style nhất quán.

Quyết định đề xuất:

- Functional icons: SVG icon component (bộ chuẩn + một số icon custom).
- Item artwork, empty state, processing illustration: PNG/WebP có alpha.
- Logo/brand mark: SVG master, có PNG export cho favicon/social nếu cần.

## 3. Art direction

- Tone: chính xác, bình tĩnh, chuyên nghiệp, "research desk" hiện đại.
- Hình học: lớp giấy, khung evidence, data nodes, page tabs; tránh robot, não, magic wand và sparkle quá mức.
- Màu: slate/navy + action blue; accent vàng evidence dùng tiết chế.
- Chất liệu: flat vector-like với texture giấy rất nhẹ, không glossy 3D.
- Không chứa text trong ảnh để tránh lỗi font/i18n.
- Hình nền trong suốt hoặc neutral để dùng được light/dark.

## 4. Asset inventory

| ID | Asset | Use | Output |
|---|---|---|---|
| ASSET-01 | Empty library | chưa có PDF | PNG/WebP alpha 1200x800 + 2x |
| ASSET-02 | Empty folder | folder trống | PNG/WebP alpha 800x600 + 2x |
| ASSET-03 | Upload processing | extraction đang chạy | 6-8 frame/Lottie hoặc CSS + static fallback |
| ASSET-04 | No search results | search/filter không có kết quả | PNG/WebP alpha |
| ASSET-05 | Document processing failed | lỗi có thể retry | PNG/WebP alpha |
| ASSET-06 | AI grounded answer | onboarding workspace | PNG/WebP alpha, không text |
| ASSET-07 | Custom document type thumbnails | PDF/table/chart/text states | SVG masters + optional PNG exports |
| ASSET-08 | Brand mark | app/login/favicon | SVG master + PNG sizes |

Không generate hàng chục asset trước khi UI layout ổn định. Bắt đầu bằng ASSET-01, 03, 07, 08 vì có mức sử dụng cao.

## 5. Functional icon system

- Chọn một library SVG làm nền, không trộn nhiều stroke language.
- Size chuẩn: 16, 20, 24; stroke optical theo size.
- Wrapper `Icon` nhận `name`, `size`, `aria-hidden`; icon-only button bắt buộc accessible label.
- Custom icons chỉ cho domain: evidence box, citation jump, data value origin, chart estimate, document revision.
- Delete/destructive không chỉ dùng màu đỏ; label/tooltip phải rõ.

## 6. Asset pipeline

```text
approved brief
  -> image generation / vector design
  -> visual review light + dark
  -> crop/background cleanup
  -> PNG master + WebP optimized
  -> asset manifest + alt policy
  -> integration + screenshot regression
```

Sử dụng image generation ở phase implementation sau khi duyệt prompt/art direction. Không generate trực tiếp vào production path mà chưa review.

## 7. File organization

```text
apps/web/src/shared/assets/
├── brand/
├── illustrations/
│   ├── empty-library/
│   ├── upload-processing/
│   └── errors/
├── document-types/
├── icons/domain/
└── manifest.ts
```

Tên file semantic, không dùng `image1-final-v2.png`. `manifest.ts` chứa dimensions, theme support, alt policy và lazy-import function.

## 8. Performance budget

- Illustration WebP thường <= 150 KB; PNG master không ship nếu WebP đủ.
- Favicon/app mark nhỏ theo chuẩn browser.
- Lazy load asset ngoài viewport/route.
- Có explicit width/height để tránh layout shift.
- Animation tôn trọng `prefers-reduced-motion` và có static fallback.
- Không nhúng base64 ảnh lớn trong JS bundle/CSS.

## 9. Accessibility

- Decorative artwork dùng alt rỗng và không lặp lại message cạnh nó.
- Informative image có alt ngắn; chi tiết trạng thái vẫn là text HTML.
- Icon-only action có label/tooltip, focus state và target 44x44 khi touch.
- Không dùng hình ảnh chứa thông tin duy nhất cần đọc.
- Contrast được kiểm tra trên cả theme.

## 10. Task breakdown

1. VIS-001: duyệt moodboard/color/type/icon language.
2. VIS-002: chốt asset brief và prompt sheet.
3. VIS-003: generate 2-3 variant cho 4 asset ưu tiên.
4. VIS-004: review/chọn/chỉnh và export master.
5. VIS-005: optimize WebP/PNG, manifest, provenance.
6. VIS-006: integrate EmptyState/FileThumbnail/ProcessingState.
7. VIS-007: dark/light/responsive/accessibility QA.
8. VIS-008: visual regression và performance budget.

## 11. Definition of Done

- Functional icon sắc nét và đồng nhất ở mọi DPI/theme.
- Asset có bản sắc SourceLens, không generic AI art.
- Không có text raster, lỗi font hoặc nền lệch theme.
- Mỗi asset có source/provenance, output sizes và usage mapping.
- Bundle/performance/accessibility budgets đạt yêu cầu.

