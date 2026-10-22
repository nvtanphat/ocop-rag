# ADR 009: Câu trả lời theo claim, cổng không nới, phiên và che định danh

## Bối cảnh
Đầu ra LLM là văn bản tự do; một claim sai làm hỏng cả câu trả lời hoặc lọt qua nhờ mã trích dẫn hợp lệ. Câu hỏi nguyên văn có tenant/dossier được lưu vào phiên và checkpoint; API debug bỏ `session_id`; thiếu khóa LLM gây HTTP 500.

## Quyết định
1. LLM trả JSON `{claims:[{text,sources}], missing:[...]}` (schema ép bằng `chat_structured`). Mỗi claim đi qua: định danh marker, kiểm điểm/sao, kiểm entailment (cổng cũ, không nới). Claim qua được công bố; claim không qua bị loại và đếm; `missing` nêu phần SOURCE không trả lời. Không claim nào qua thì quay về bản trích xuất như trước. Nguồn chưa duyệt vẫn không được công bố là đã kiểm.
2. Kiểm độ phủ trên **đúng** khối SOURCE gửi LLM; thiếu thuật ngữ câu hỏi dưới ngưỡng thì không sinh.
3. `SessionStore` dùng chung cho API công khai và debug; `last_query` được che bằng `configs/ocop_privacy.yaml` trước khi lưu; checkpoint LangGraph cũng nhận câu hỏi đã che. Câu hỏi riêng tư không bao giờ vào checkpoint.
4. Lỗi cấu hình/hạ tầng trả 503 với thân cố định `{code, layer, error_type, message}`, không lặp lại nội dung ngoại lệ.
5. `tools_used` chỉ liệt kê công cụ đã chạy; `tools_skipped` liệt kê bước bị bỏ do phụ thuộc.

## Cập nhật: tầng "chưa duyệt" có kiểm chứng căn cứ

Chặn mọi claim chỉ vì nguồn chưa duyệt khiến hệ thống chỉ trả lại đoạn OCR. Hiện có hai tầng, tách bạch trong kết quả:
* **verified**: nguồn `verified` + marker + entailment (không đổi).
* **unreviewed**: nguồn chưa duyệt; claim chỉ được hiển thị, kèm nhãn "[LƯU Ý: Nguồn OCR/trích xuất chưa được duyệt]" và trạng thái `generated_unverified_claims`, khi qua `grounded_in_excerpt` trên **hợp** các đoạn nó trích: mọi con số có trong đoạn, phủ định khớp, ≥80% từ nội dung có trong đoạn (≥90% với claim quan trọng) và có một chuỗi từ liên tiếp trùng đoạn.
* **Cổng điểm/sao không nới**: điểm hoặc sao của một sản phẩm từ nguồn chưa duyệt vẫn bị chặn. Chỉ quy tắc pháp lý chung (ví dụ "UBND cấp tỉnh công nhận sản phẩm 3 sao, 4 sao") được hiển thị, và chỉ khi đoạn trích là văn bản thường, không có sản phẩm/chủ thể trong danh mục xuất hiện và có danh mục thực thể để kiểm.
* Claim về trạng thái duyệt ("OCR chưa xác minh") không phải nội dung; hệ thống tự gắn nhãn.

## Dự án đã tham khảo
| Dự án / tài liệu | Ngày đọc | Ý tưởng | Quyết định |
| --- | --- | --- | --- |
| ALCE (Gao và cộng sự, EMNLP 2023) | 2026-10-22 | Đo citation recall/precision theo từng phát biểu bằng NLI | Áp dụng đơn vị "claim"; chưa dùng NLI vì không có bộ kiểm audited, giữ kiểm tất định |
| LlamaIndex `CitationQueryEngine` | 2026-10-22 | Mỗi nhận định gắn mã nguồn | Đã tương đương bằng `[S#]`; thêm JSON claims |
| Self-RAG / CRAG | 2026-10-22 | Tự đánh giá đủ/thiếu bằng chứng | Áp dụng thành `missing` và kiểm độ phủ tất định, không dùng LLM tự chấm |
| RAGAS, ARES | 2026-10-22 | Cách đo faithfulness/context relevance | Chỉ tham khảo cách đo; không thay bộ đo ảnh PDF |

## Hệ quả
Trên corpus chưa có bằng chứng `verified`, số câu LLM được công bố vẫn là 0; chỉ người duyệt Markdown (HUMAN_REVIEW.md) mới mở được.
