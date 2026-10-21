# Thuật ngữ Miền OCOP GraphRAG (Domain Glossary)

Tài liệu định nghĩa các khái niệm cốt lõi trong hệ thống OCOP GraphRAG. Mọi tầng trích xuất, lưu trữ đồ thị, tìm kiếm và giao diện đều tuân thủ các thuật ngữ này.

---

### 1. Thực thể và Dữ liệu Nguồn

* **`SourceDocument`**: Văn bản pháp quy hoặc quyết định công nhận OCOP gốc. Mỗi văn bản được quản lý bằng `source_id` duy nhất (ví dụ: `VN.OCOP.QD26.2026`), định danh trong `configs/ocop_sources.json` và khóa băm SHA-256 bất biến trong `configs/ocop_sources.lock.json`.
* **`EvidenceUnit`**: Đơn vị bằng chứng nguyên tử trích xuất từ PDF gốc. Mỗi `EvidenceUnit` mang mã `unit_id` tiền tố `ocop:evidence:`, đại diện cho đoạn văn bản, bảng biểu, hoặc dòng bảng, luôn bảo lưu tọa độ hộp bao (`bbox`), số trang PDF (`pdf_page`), mã văn bản (`source_id`), và mã băm nguồn (`source_sha256`).
* **`CriterionSheet`**: Bộ phiếu tiêu chí đánh giá và phân hạng sản phẩm OCOP theo ngành/nhóm sản phẩm (ví dụ: thực phẩm tươi sống, đồ uống, thảo dược). Mỗi phiếu chứa danh sách các tiêu chí thành phần và điểm tối đa tương ứng.
* **`Criterion` / `Subcriterion`**: Tiêu chí hoặc tiêu chí con trong bảng chấm điểm OCOP, gắn với mã mục (ví dụ: `1.1`, `2.1`) và mức điểm thành phần.
* **`RecognitionRecord`**: Bản ghi công nhận kết quả xếp hạng sao OCOP cho một sản phẩm và chủ thể cụ thể tại một địa phương, trích xuất từ quyết định UBND.
* **`FormTemplate` / `FormField`**: Cấu trúc mẫu biểu hồ sơ (ví dụ: Mẫu số 01, Mẫu 02) và các trường thông tin thủ tục bắt buộc mà chủ thể OCOP cần hoàn thiện.

---

### 2. Thuộc tính Kiểm chứng và Nguồn gốc (Provenance & Checks)

* **`origin`**: Phân loại nguồn gốc phát sinh của thực thể hoặc quan hệ:
  * `deterministic`: Trích xuất dựa trên quy tắc tất định từ văn bản hoặc cấu trúc bảng gốc.
  * `llm`: Đề xuất suy luận ngữ nghĩa bởi mô hình ngôn ngữ từ các bằng chứng cụ thể.
  * `human`: Bổ sung hoặc xác nhận trực tiếp từ chuyên gia thẩm định.
* **`check`**: Trạng thái kiểm chứng kỹ thuật của nút hoặc cạnh trên đồ thị:
  * `passed`: Đạt toàn bộ các ràng buộc về hình học tọa độ, mã SHA nguồn, tính toàn vẹn liên kết và schema.
  * `failed`: Vi phạm ít nhất một ràng buộc kỹ thuật; bị loại khỏi đồ thị công khai và truy vấn runtime.
  * `human_verified`: Đã được con người kiểm tra và xác nhận hợp lệ qua nhật ký thẩm định.
* **`review_status`**: Mức độ tin cậy nghiệp vụ của bằng chứng và thực thể:
  * `candidate` / `needs_review`: Dữ liệu thô từ OCR hoặc suy luận mô hình; cần con người duyệt trước khi dùng làm kết luận khẳng định.
  * `verified` / `human_verified`: Dữ liệu đã được đối chiếu hoặc chuyên gia thẩm định xác nhận.
  * `rejected`: Dữ liệu bị bác bỏ, không tham gia vào quá trình tính điểm hay đánh giá.

---

### 3. Quy trình Thẩm định và Vận hành

* **`Review Ledger`**: Nhật ký bất biến lưu trữ quyết định duyệt của con người tại `data/review/ocop_review_decisions.jsonl`. Mọi thay đổi đều được ghi nối tiếp kèm dấu thời gian và người duyệt; không sửa đè lịch sử.
* **`Fail-Closed Citation Gate`**: Cổng chặn an toàn trong tầng sinh câu trả lời: câu trả lời bắt buộc phải có trích dẫn marker `[S#]` trỏ tới `EvidenceUnit` hợp lệ với đúng mã băm `source_sha256` và tọa độ hình học. Mọi câu trả lời thiếu trích dẫn hoặc viện dẫn sai đều bị từ chối công bố.
