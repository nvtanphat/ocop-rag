# Thuật ngữ miền OCOP GraphRAG

Một ngữ cảnh miền thống nhất cho nguồn OCOP, bằng chứng, tri thức và kết quả tra cứu.

## Nguồn và tri thức

**SourceDocument**: Văn bản gốc thuộc danh mục OCOP được phê duyệt, có danh tính và mã SHA-256 xác định duy nhất nội dung PDF.

**EvidenceUnit**: Đơn vị bằng chứng trích từ nguồn, có định danh và một hoặc nhiều vùng trên trang PDF gốc. Mỗi vùng giữ trang, bbox và SHA nguồn để đối soát.

**Provenance**: Dấu vết nối một nội dung với danh tính nguồn, bằng chứng, trang, vùng và bytes nguồn gốc. Provenance hợp lệ không tự chứng minh nội dung được suy ra đúng nghĩa.

**CriterionSheet**: Phiếu tiêu chí đánh giá cho một ngành hoặc nhóm sản phẩm OCOP.

**Criterion / Subcriterion**: Tiêu chí hoặc tiêu chí con thuộc phiếu đánh giá, có nội dung và điều kiện áp dụng từ nguồn.

**RecognitionRecord**: Kết quả công nhận OCOP đối với sản phẩm và chủ thể cụ thể tại một địa phương; không đồng nhất với ứng viên OCR của bảng công nhận.

**FormTemplate / FormField**: Mẫu biểu và trường thông tin trong hồ sơ thủ tục OCOP.

**Quy tắc tham chiếu đã xác minh**: Quy định đã được đối chiếu nguồn, có căn cứ và đúng phiên bản corpus đang dùng. Quy tắc do người dùng hoặc mô hình tự đề xuất không thuộc khái niệm này.

## Trạng thái và kiểm chứng

**origin**: Nguồn hình thành tri thức: trích xuất tất định (`deterministic`), đề xuất mô hình (`llm`) hoặc con người (`human`). Nguồn hình thành không phải mức độ xác minh.

**check**: Kết quả kiểm kỹ thuật của đối tượng đồ thị: `passed`, `failed` hoặc `human_verified`. Đạt kiểm kỹ thuật không tự đồng nghĩa được xác minh về nghiệp vụ.

**review_status**: Trạng thái duyệt nội dung: ứng viên/chưa duyệt (`candidate`, `needs_review`), đã xác minh (`verified`, `human_verified`) hoặc bị bác bỏ (`rejected`). Điểm/sao chưa được duyệt không dùng để kết luận xếp hạng.

**Review Ledger**: Nhật ký nối tiếp các quyết định duyệt, bác bỏ hoặc hiệu chỉnh, gắn với người duyệt và đúng nội dung được đối soát. Quyết định mới không xoá lịch sử cũ.

**Claim**: Một nhận định có căn cứ trích dẫn, được kiểm và công bố độc lập trong câu trả lời.

**Fail-Closed Citation Gate**: Cổng từ chối công bố nhận định khi thiếu điều kiện kiểm chứng trích dẫn, căn cứ hoặc điểm/sao. Marker hợp lệ chỉ là một trong các điều kiện.

## Phiên bản và truy xuất

**Corpus active**: Tập dẫn xuất nguồn đang được hệ thống dùng để tra cứu. Phiên bản corpus không tự xác định văn bản nào có hiệu lực tại một năm lịch sử.

**Quyết định đã ghim**: Phiên bản văn bản được người hỏi chọn rõ ràng; một thay đổi về năm lịch sử không được âm thầm thay thế lựa chọn đó.

**Danh mục thực thể**: Danh sách văn bản, địa danh, sản phẩm, chủ thể, cơ quan, phiếu và mẫu có căn cứ từ corpus.

**Chuỗi cha**: Ngữ cảnh tổ tiên trực tiếp của một đoạn nguồn, ví dụ Điều và khoản; phân biệt với nội dung nguyên văn của đoạn.

**Năng lực chính / phụ**: Năng lực chính trả lời yêu cầu; năng lực phụ chỉ bổ sung và không được tự tạo căn cứ còn thiếu.

**Bộ giữ riêng**: Bộ câu hỏi độc lập đã khoá trước khi đánh giá, không dùng để điều chỉnh hệ thống theo từng câu.
