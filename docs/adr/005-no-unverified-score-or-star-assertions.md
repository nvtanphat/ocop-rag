# ADR 005: Không dùng điểm hoặc xếp hạng sao chưa xác minh làm căn cứ chính thức

## Bối cảnh
Các bảng biểu điểm và tiêu chí trong văn bản OCOP thường có định dạng phức tạp, chữ viết tay, hoặc dấu tích chấm điểm thực địa. OCR tự động có thể nhận diện sai số điểm hoặc đọc nhầm dấu hoa thị (`*`), dẫn đến việc tính sai tổng điểm hoặc xếp hạng sai sản phẩm OCOP nếu tin cậy tuyệt đối vào OCR.

## Quyết định
* Tách biệt hoàn toàn giữa ứng viên số liệu (`candidate` / `needs_review`) và sự kiện miền đã được kiểm chứng (`verified` / `human_verified`).
* Cấm sử dụng các giá trị điểm số hoặc số sao chưa xác minh để xếp hạng sản phẩm hoặc đánh giá hồ sơ chính thức.
* Mọi quy tắc và tiêu chuẩn dùng để thẩm định hồ sơ (`checklist`, `review_dossier`) bắt buộc phải đọc từ các quy định tham chiếu đã xác minh (`verified_requirements.jsonl`, `verified_criteria.jsonl`), không bao giờ dùng quy tắc do phía người dùng hay LLM tự đưa vào.

## Hệ quả
* Bảo vệ tính pháp lý của quy trình đánh giá sản phẩm OCOP.
* Định hướng rõ ràng cho công tác thẩm định của con người: chỉ tập trung vào các bằng chứng mang cờ `needs_review`.
