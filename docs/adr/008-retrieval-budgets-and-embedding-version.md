# ADR 008: Ngân sách truy xuất cấu hình được, phiên bản thư viện nhúng và rerank trên CPU

## Bối cảnh
* Mô hình nhúng cần attention hai chiều; với `transformers` quá cũ nó chạy attention nhân quả và vector suy giảm, làm truy xuất hybrid kém hơn sparse.
* Truy vấn dense quá dài bị cắt ngầm, lỗi hạ tầng vector có thể thoát khỏi nhánh dự phòng, và rerank trên CPU rất chậm nếu không có ngân sách.

## Quyết định
1. `transformers>=4.57,<5`; `configs/ocop_models.yaml` khai báo `embedding.min_transformers_version` và được kiểm khi nạp mô hình. Đổi phiên bản thư viện nhúng thì dựng lại chỉ mục dense.
2. Truy vấn dense được đếm bằng tokenizer thật; vượt `max_seq_length` thì rút gọn theo từ, ghi `query_truncated` và số token.
3. Mọi lỗi mô hình/hạ tầng ở nhánh dense rơi về sparse với `dense_unavailable:<loại lỗi>`.
4. Tham số truy xuất (RRF k và trọng số, kích thước pool, số ứng viên rerank, batch, số luồng, cache) nằm ở `configs/ocop_retrieval.yaml`.
5. Rerank: tối đa `rerank_candidates` cặp; `max_length` bằng ngân sách cặp (cặp quá dài bị cắt và gắn cờ `rerank_input_truncated`); batch nhỏ; luồng torch theo cấu hình; cache điểm LRU theo mô hình/câu hỏi/đoạn. Cờ rerank áp dụng cho cả nhánh tìm trong phiếu và trong Điều.
6. Không dùng ONNX/int8: bản ONNX của bge-reranker-v2-m3 chỉ do cộng đồng phát hành, lượng tử hóa động của torch không ổn định với bản transformers được ghim, và chất lượng sau lượng tử hóa chưa được đo.

## Hệ quả
Các danh sách tại `SCHEMA_REVISION` và `INDEX_VERSION` xác định mã làm đổi phiên bản
graph/chỉ mục; xem [vân tay mã nguồn](../DEVELOPMENT.md#vân-tay-mã-nguồn). Mã runtime
ngoài các danh sách đó không tự yêu cầu dựng lại.
