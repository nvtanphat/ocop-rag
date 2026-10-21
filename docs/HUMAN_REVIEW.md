# Hướng dẫn Quy trình Thẩm định của Con người (Human Review Guide)

Tài liệu hướng dẫn quy trình đối soát, phê duyệt dữ liệu từ ứng viên máy (machine candidates) thành tri thức miền đã xác thực (`human_verified`), cấu trúc nhật ký quyết định (Review Ledger) và các công cụ hỗ trợ thẩm định.

---

## 1. Mục đích và Nguyên tắc Thẩm định

### Mục đích
Quá trình nhận dạng ký tự (OCR) trên các trang scan phức tạp, bảng biểu chấm điểm OCOP, hoặc các thực thể do mô hình ngôn ngữ (LLM) đề xuất có thể chứa sai sót hoặc chưa đủ căn cứ pháp lý. Các đối tượng này được gán nhãn `needs_review` hoặc `candidate`. Quy trình Human Review cho phép chuyên gia thẩm định kiểm tra trực quan với tài liệu gốc và xác nhận tính hợp lệ.

### Nguyên tắc Bất biến
1. **Không sửa đè tài liệu gốc**: Dữ liệu PDF gốc và các file trích xuất OCR nguyên thủy không bao giờ bị can thiệp.
2. **Nhật ký bất biến nối tiếp (Append-Only Ledger)**: Mọi quyết định phê duyệt (`approve`), từ chối (`reject`) hoặc hiệu chỉnh (`correct`) đều được ghi nối tiếp vào tệp `data/review/ocop_review_decisions.jsonl`.
3. **Phân định rõ thẩm quyền**: Mọi bản ghi quyết định bắt buộc phải có định danh người thẩm định (`reviewer`), dấu thời gian kèm múi giờ (`timestamp` ISO 8601), và mã băm toàn vẹn của đối tượng (`content_hash`).

---

## 2. Cấu trúc Bản ghi Quyết định (Review Ledger)

Tệp lưu trữ: `data/review/ocop_review_decisions.jsonl`.

Mỗi dòng là một đối tượng JSON đại diện cho một sự kiện thẩm định:

```json
{
  "target_id": "ocop:evidence:756a04e519e8c828690d6dfd",
  "content_hash": "b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb",
  "decision": "approve",
  "reviewer": "chuyengia_ocop_01",
  "timestamp": "2026-10-21T10:30:00+07:00",
  "notes": "Đã đối chiếu bảng điểm tại trang 3 quyết định Hải Phòng",
  "correction": null
}
```

* **Các trường dữ liệu**:
  * `target_id`: Mã định danh duy nhất của nút, cạnh, hoặc bằng chứng cần thẩm định.
  * `content_hash`: Mã băm SHA-256 nội dung của đối tượng tại thời điểm xem xét (chống việc phê duyệt nhầm phiên bản đã thay đổi).
  * `decision`: Quyết định thẩm định, gồm `approve` (chấp thuận), `reject` (bác bỏ), hoặc `correct` (hiệu chỉnh).
  * `reviewer`: Tên hoặc mã định danh của chuyên gia thực hiện duyệt.
  * `timestamp`: Thời điểm ra quyết định theo định dạng ISO 8601 (bắt buộc có timezone).
  * `notes`: Ghi chú căn cứ hoặc lý do thẩm định.
  * `correction`: Đối tượng dữ liệu hiệu chỉnh nếu quyết định là `correct`.

---

## 3. Quy trình Thẩm định qua Dòng lệnh (CLI Workflow)

### Bước 1: Kiểm tra Thống kê Hàng đợi Thẩm định
```powershell
python tools/cli.py review stats
```
Lệnh hiển thị tổng số mục cần duyệt, phân bổ theo độ ưu tiên (`high`, `medium`, `low`) và theo loại thực thể.

### Bước 2: Xuất Hàng đợi và Kết xuất Ảnh Cắt Đối soát (Crop Rendering)
```powershell
python tools/cli.py review queue --out data/review/ocop_review_queue.jsonl --render
```
* Cờ `--render` sẽ tự động cắt ảnh độ phân giải 300 DPI từ đúng tọa độ `bbox` của bằng chứng trên PDF gốc và lưu vào thư mục `data/review/crops/`.
* Tệp `ocop_review_queue.jsonl` được tạo ra chứa đầy đủ danh sách các mục chờ duyệt kèm đường dẫn ảnh đối soát.

### Bước 3: Ghi nhận Quyết định Thẩm định
```powershell
# Phê duyệt đối tượng
python tools/cli.py review decide `
  --target-id "ocop:evidence:756a04e519e8c828690d6dfd" `
  --content-hash "b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb" `
  --decision approve `
  --reviewer "chuyengia_01" `
  --notes "Khớp văn bản gốc"

# Bác bỏ đối tượng
python tools/cli.py review decide `
  --target-id "ocop:evidence:..." `
  --content-hash "..." `
  --decision reject `
  --reviewer "chuyengia_01" `
  --notes "Ký tự OCR lỗi không thể phục hồi"
```

### Bước 4: Tự động Tái cấu trúc Đồ thị (Rebuild Graph)
Khi lệnh `decide` hoàn tất, hệ thống tự động kích hoạt hàm `rebuild_reviewed_graph`:
1. Nạp quyết định mới nhất cho từng `target_id`.
2. Nâng cấp trạng thái các nút/cạnh được phê duyệt từ `needs_review` sang `human_verified` (`check: human_verified`).
3. Loại bỏ các nút/cạnh bị bác bỏ khỏi đồ thị tra cứu.
4. Sinh lại snapshot đồ thị mới kèm chữ ký số và cập nhật `manifest.json`.

---

## 4. Giao diện Thẩm định Web (Frontend Review)

Hệ thống tích hợp màn hình thẩm định trực quan tại tab **Review** trên giao diện React (`frontend/src/ocop/Review.tsx`):
* **Xem bằng chứng trực quan**: Hiển thị song song thông tin thực thể, trích đoạn văn bản và ảnh chụp crop từ PDF gốc.
* **Mở trang PDF gốc**: Liên kết trực tiếp tới `/api/ocop/sources/<source_id>/pdf#page=<page>` để đối soát ngữ cảnh toàn trang.
* **Xác thực an toàn**: Giao diện yêu cầu nhập mã `OCOP_REVIEW_TOKEN` để gọi API POST `/api/ocop/review/decisions`, ngăn chặn các thao tác duyệt trái phép.
