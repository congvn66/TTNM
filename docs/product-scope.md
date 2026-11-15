# Pham vi san pham MVP

Tai lieu nay quyet dinh boundary. Requirement co the test va acceptance criteria nam trong `requirements.md`; quy tac nghiep vu nam trong `domain-rules.md`.

## 1. Tom tat

Ung dung web cho phep mot nguoi dung tai bao cao PDF tieng Viet, dat cau hoi ve van ban, bang va bieu do, kiem tra tung can cu tren PDF, xem du lieu/cach tinh, sua mot gia tri trich xuat trong phien tro chuyen va nhan cac cau tra loi phu thuoc da duoc tinh lai.

Gia tri khac biet khong nam o chat tong quat, ma o ba kha nang co the kiem chung:

1. Moi y ket luan truy nguoc duoc den vung nguon va ban can cu cu the.
2. Moi phep tinh luu input, don vi, cong thuc va pham vi so sanh.
3. Moi chinh sua tao lich su rieng cua chat va cap nhat dung tap ket qua bi anh huong.

## 2. Nguoi dung va cong viec

- Sinh vien/hoc vien trich so lieu de dua vao bai lam.
- Chuyen vien phan tich so sanh chi tieu va giai thich ket qua.

Cong viec cot loi: tra mot gia tri; so sanh/tinh tong/hieu/phan tram; ket hop giai thich van ban voi so lieu; hoi noi tiep; kiem tra va sua can cu.

## 3. Dau vao va dau ra

### Dau vao ho tro

- PDF tieng Viet, 2-10 trang.
- Van ban, bang co mot hang tieu de.
- Bieu do cot nhom hoac duong, truc tuyen tinh, toi da 3 series.
- Cau hoi tieng Viet.

### Dau ra bat buoc

- Cau tra loi co trang thai: `answered`, `needs_clarification`, `insufficient_data`, `source_conflict` hoac `processing_error`.
- Tung claim co can cu: trang, bbox neu co, gia tri/van ban, don vi, ky va cach trich xuat.
- Phep tinh co operation, input chinh xac, cong thuc, pham vi va quy tac lam tron.
- Du lieu co `data_status` rieng voi `verification_status`.
- Sua du lieu hien gia tri goc, ban dang dung, ly do va lich su; cau tra loi cu van mo lai duoc.

## 4. Trong pham vi MVP

- Tai khoan ca nhan, dang nhap, dat lai mat khau.
- Project, document, document version va chat da luu.
- Nap PDF, trich xuat text/table/region; OCR cho trang scan khi adapter ho tro.
- Chon bieu do sau khi hieu cau hoi; doc nhan truc tiep hoac uoc luong theo truc va gan provenance.
- Tra cuu, tong, hieu, so sanh, xep hang va phan tram thay doi.
- Phan biet 0 voi missing; xu ly mau so 0, don vi khong tuong thich, dong hang.
- Can cu bat bien, revision trong chat, answer revision, pin va mo lai lich su.
- Dieu huong bang ban phim va focus co du doan trong cac luong chinh.
- Benchmark ky thuat va thu nghiem nguoi dung nho theo tai lieu dataset/test.

## 5. Ngoai pham vi ban dau

- Dinh dang ngoai PDF; chinh sua file goc; tom tat bao cao tong quat.
- Tai lieu dai hon 10 trang hoac bieu do ngoai hai loai da chon.
- Hop nhat/mau thuan giua nhieu tai lieu trong mot cau tra loi.
- Tu dong "sua" du lieu sai ma khong co nguoi dung xac nhan.
- Cam ket pixel-level attribution cho tung diem bieu do.
- Multi-tenant organization, chia se/collaboration thoi gian thuc.

## 6. Tieu chi thanh cong MVP

### Chuc nang

- Hoan thanh 5 kich ban vang trong `test-roadmap.md` tren bo PDF pham vi.
- Sua mot can cu chi thay doi chat do; cau tra loi phu thuoc duoc danh dau va tinh lai, cau khong lien quan khong doi.
- Mo lai ban tra loi cu cho thay dung input cu.

### Ky thuat/AI

- Bao cao rieng do dung value, unit, period, source link va action selection.
- Bao cao hai che do: pipeline tu trich xuat va oracle input de tach loi doc voi loi suy luan/tinh.
- Nguong cu the duoc chot tren dev set truoc khi mo final set.

### Van hanh va UX

- Ghi median/p95 cho upload, extract va answer; chi phi theo tai lieu/cau hoi.
- Khong co loi nghiem trong tren cac luong giao dien chinh va keyboard smoke test.
- Thu nghiem 5-10 nguoi chi mo ta xu huong, khong khang dinh nhan qua rieng tung tinh nang.

## 7. Gia dinh can xac thuc

- Docling (hoac adapter thay the) tra ve bbox on dinh cho PDF tieng Viet.
- Chat extraction co the tri hoan den khi biet bieu do lien quan ma van dap ung latency.
- PostgreSQL du cho hang doi MVP; neu workload yeu cau moi them broker rieng.
- Provider LLM/VLM va chinh sach gui du lieu chua duoc chot.

## 8. Actor va quyen

MVP co mot actor san pham: `authenticated user`. User chi quan ly project/document/chat cua minh. Worker/provider la system actor, khong co quyen vuot owner scope; moi job mang owner/resource IDs va publish lai kiem quyen.

Khong co admin UI, organization, sharing, role management hay collaboration trong MVP.

## 9. Boundary voi AI

- AI/parser co the de xuat question context, candidate evidence, chart values va answer wording.
- Rule/schema validator quyet dinh output co duoc ghi/dung hay khong.
- Calculator code quyet dinh numeric result.
- AI khong duoc tu sua raw evidence, bo qua missing/conflict, hoac publish ket qua khi fence cu.

## 10. Definition of MVP accepted

MVP chi duoc coi la dat khi:

1. Tat ca MUST requirements trong `requirements.md` co test hoac waiver/ADR.
2. `scripts/run_flow_tests.py` pass va backend integration/E2E gates tuong ung pass.
3. Khong co P0/P1 mo.
4. Privacy/provider/retention P0 duoc chot.
5. Final benchmark chay theo manifest/config da freeze, khong sua gold sau khi mo tap.
