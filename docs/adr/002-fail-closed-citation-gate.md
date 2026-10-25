# ADR 002: Cổng kiểm tra trích dẫn đóng ngắt (Fail-Closed Citation Gate)

## Bối cảnh
Mô hình sinh ngôn ngữ lớn (LLM) có thể tạo ảo giác (hallucination) hoặc bịa đặt số liệu/văn bản viện dẫn không có thật trong tài liệu gốc OCOP, gây rủi ro pháp lý nghiêm trọng.

## Quyết định
* Triển khai cơ chế kiểm tra trích dẫn nghiêm ngặt (fail-closed) tại tầng hậu xử lý câu trả lời (`ai_core/orchestration/ocop/verification.py`):
  1. Mọi nhận định trong câu trả lời phải gắn với chỉ dẫn trích dẫn định dạng `[S#]`.
  2. Mỗi chỉ dẫn `[S#]` phải đối soát thành công với một `EvidenceUnit` có thật trong kết quả tìm kiếm.
  3. Mã băm SHA-256 (`source_sha256`) và tọa độ hình học (`bbox` / `table_bbox`) của bằng chứng phải khớp tuyệt đối với văn bản PDF gốc.
* Nếu câu trả lời viện dẫn sai marker, trỏ tới bằng chứng không tồn tại, hoặc sai lệch mã băm, cổng bảo vệ sẽ từ chối công bố câu trả lời và hạ cấp về chế độ an toàn (`citation_verification_failed` hoặc trả về trích dẫn thuần túy `retrieval_only`).

## Hệ quả
* Chặn trích dẫn sai định danh/provenance; không chứng minh ngữ nghĩa đúng chỉ bằng marker hợp lệ. Tuyên bố cũ “ngăn chặn 100% rủi ro” đã được **Superseded** bởi phạm vi kiểm chứng từng claim trong ADR-009.
* Đảm bảo tính giải trình: mọi câu trả lời người dùng nhận được đều có thể truy vết về chính xác trang và tọa độ trên file PDF gốc.
