# ADR 009: Câu trả lời theo claim, cổng không nới, phiên và che định danh

Trạng thái: Accepted.

## Bối cảnh
Đầu ra LLM là văn bản tự do: một claim sai làm hỏng cả câu trả lời, hoặc lọt qua nhờ mã trích dẫn hợp lệ. Câu hỏi nguyên văn có thể chứa tenant/hồ sơ nên không được lưu thô vào phiên và checkpoint. Thiếu khóa LLM phải là lỗi hạ tầng có kiểm soát, không phải HTTP 500.

## Quyết định
1. LLM trả JSON `{claims:[{text,sources,quote}], missing:[...]}` qua `chat_structured`; mọi thuộc tính schema đều thuộc `required`. Quote phải nguyên văn, dài tối thiểu 15 ký tự. Mỗi claim đi qua định danh marker, kiểm số/phủ định, cổng điểm/sao và kiểm nghĩa. Claim qua được thì công bố; claim không qua bị loại và đếm; `missing` nêu phần SOURCE không trả lời. Không claim nào qua thì quay về bản trích xuất.
2. Kiểm độ phủ trên đúng khối SOURCE gửi LLM; thiếu thuật ngữ câu hỏi dưới ngưỡng thì không sinh.
3. API công khai dùng `SessionStore`; `last_query` được che bằng `configs/ocop_privacy.yaml` trước khi lưu; checkpoint LangGraph cũng nhận câu hỏi đã che. Câu hỏi riêng tư không bao giờ vào checkpoint. Test dùng ứng dụng thật với fixture cô lập.
4. Lỗi cấu hình/hạ tầng trả 503 với thân cố định `{code, layer, error_type, message}`, không lặp lại nội dung ngoại lệ.
5. `tools_used` chỉ liệt kê công cụ đã chạy; `tools_skipped` liệt kê bước bị bỏ do phụ thuộc.

## Kiểm nghĩa từng phát biểu

Quote hợp lệ chỉ chứng minh vị trí nguồn. Diễn đạt lại phải qua lượt xét nghĩa
riêng với quote nằm trong đoạn gốc; độ phủ từ vựng không đủ để chấp nhận claim.
Số được gắn với nhãn đại lượng, không được miễn kiểm vì xuất hiện trong câu hỏi.
`resolved_locator` bổ sung nhãn vị trí từ công cụ, không thay thế thân quote.
Cổng điểm/sao vẫn tuân theo [ADR-005](005-no-unverified-score-or-star-assertions.md).

## Hệ quả
Lượt xét nghĩa làm tăng độ trễ; lỗi marker, quote hoặc điểm/sao không được lượt
xét lại bỏ qua. Kết quả kiểm chứng được giữ theo từng claim để truy nguyên lỗi.
Số đo lịch sử nằm trong [tổng hợp kiểm tra runtime](../RUNTIME_AUDIT.md).
