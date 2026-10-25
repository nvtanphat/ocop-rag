# ADR 009: Câu trả lời theo claim, cổng không nới, phiên và che định danh

Trạng thái: Accepted.

## Bối cảnh
Đầu ra LLM là văn bản tự do: một claim sai làm hỏng cả câu trả lời, hoặc lọt qua nhờ mã trích dẫn hợp lệ. Câu hỏi nguyên văn có thể chứa tenant/hồ sơ nên không được lưu thô vào phiên và checkpoint. Thiếu khóa LLM phải là lỗi hạ tầng có kiểm soát, không phải HTTP 500.

## Quyết định
1. LLM trả JSON `{claims:[{text,sources}], missing:[...]}` (schema ép bằng `chat_structured`). Mỗi claim đi qua: định danh marker, kiểm điểm/sao, kiểm entailment. Claim qua được thì công bố; claim không qua bị loại và đếm; `missing` nêu phần SOURCE không trả lời. Không claim nào qua thì quay về bản trích xuất. Nguồn chưa duyệt không được công bố là đã kiểm.
2. Kiểm độ phủ trên đúng khối SOURCE gửi LLM; thiếu thuật ngữ câu hỏi dưới ngưỡng thì không sinh.
3. API công khai dùng `SessionStore`; `last_query` được che bằng `configs/ocop_privacy.yaml` trước khi lưu; checkpoint LangGraph cũng nhận câu hỏi đã che. Câu hỏi riêng tư không bao giờ vào checkpoint. Test dùng ứng dụng thật với fixture cô lập.
4. Lỗi cấu hình/hạ tầng trả 503 với thân cố định `{code, layer, error_type, message}`, không lặp lại nội dung ngoại lệ.
5. `tools_used` chỉ liệt kê công cụ đã chạy; `tools_skipped` liệt kê bước bị bỏ do phụ thuộc.

## Hai tầng nguồn
Chặn mọi claim chỉ vì nguồn chưa duyệt sẽ chỉ còn trả lại đoạn OCR, nên kết quả có hai tầng tách bạch:
* **verified**: nguồn `verified` + marker + entailment.
* **unreviewed**: nguồn chưa duyệt. Claim chỉ được hiển thị, kèm nhãn "[LƯU Ý: Nguồn OCR/trích xuất chưa được duyệt]" và trạng thái `generated_unverified_claims`, khi qua `grounded_in_excerpt` trên hợp các đoạn nó trích: mọi con số có trong đoạn, phủ định khớp, ≥80% từ nội dung có trong đoạn (≥90% với claim quan trọng) và có một chuỗi từ liên tiếp trùng đoạn.
* **Cổng điểm/sao không nới**: điểm hoặc sao của một sản phẩm từ nguồn chưa duyệt luôn bị chặn. Chỉ quy tắc pháp lý chung (ví dụ "UBND cấp tỉnh công nhận sản phẩm 3 sao, 4 sao") được hiển thị, và chỉ khi đoạn trích là văn bản thường, không chứa sản phẩm/chủ thể trong danh mục và có danh mục thực thể để kiểm.
* Claim về trạng thái duyệt ("OCR chưa xác minh") không phải nội dung; hệ thống tự gắn nhãn.

## Hệ quả
Nguồn chưa duyệt không được công bố như nguồn verified. Câu trả lời có căn cứ nhưng chưa duyệt mang nhãn theo chính sách trên; điểm/sao sản phẩm vẫn bị chặn. Hướng dẫn review qua CLI và dataset OCR nằm trong [RUNBOOK](../RUNBOOK.md) và [ocr/README.md](../../ocr/README.md).
