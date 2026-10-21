# ADR 008: Ngân sách truy xuất cấu hình được, phiên bản thư viện nhúng và rerank trên CPU

## Bối cảnh
* Cảnh báo `use_bidirectional_attention` với transformers 4.51.3: mô hình nhúng chạy attention nhân quả, vector suy giảm; trên bộ giữ riêng hybrid top-1 thấp hơn sparse (23/36 so với 26/36).
* Câu hỏi dense dài bị cắt ngầm; mất Qdrant làm exception thoát khỏi nhánh dự phòng; cờ rerank bị bỏ ở hai nhánh tìm; rerank 157–163 giây mỗi câu trên máy 6 nhân.

## Quyết định
1. `transformers>=4.57,<5` (đã chạy 4.57.6); `configs/ocop_models.yaml` khai báo `embedding.min_transformers_version`, kiểm khi nạp mô hình; dựng lại chỉ mục dense. Kết quả đo: hybrid top-1 giữ riêng 23/36 → 28/36.
2. Truy vấn dense được đếm bằng tokenizer thật; vượt `max_seq_length` thì rút gọn theo từ có ghi `query_truncated` và số token, không cắt ngầm.
3. Mọi lỗi mô hình/hạ tầng ở nhánh dense rơi về sparse với `dense_unavailable:<loại lỗi>`.
4. Tham số truy xuất (RRF k và trọng số, kích thước pool, số ứng viên rerank, batch, số luồng, cache) ở `configs/ocop_retrieval.yaml`.
5. Rerank: tối đa `rerank_candidates` cặp, `max_length` bằng ngân sách cặp (cặp quá dài bị cắt có cờ `rerank_input_truncated`, không còn là lỗi), batch nhỏ, luồng torch theo cấu hình, cache điểm LRU theo mô hình/câu hỏi/đoạn. Cờ rerank đi qua cả nhánh tìm trong phiếu và Điều.
6. Không dùng ONNX/int8: bản ONNX của bge-reranker-v2-m3 chỉ do cộng đồng phát hành, chưa có bản chính thức, và lượng tử hóa động của torch lỗi với bản transformers đã ghim; chất lượng sau lượng tử hóa chưa được đo.

## Dự án đã tham khảo
| Dự án | Ngày đọc | Ý tưởng | Quyết định |
| --- | --- | --- | --- |
| Haystack `DocumentJoiner` (RRF) + ranker | 2026-10-22 | BM25 và vector song song, hợp nhất bằng RRF, rerank cross-encoder rồi mới cắt top-k | Cùng mô hình xử lý; RRF tự cài (vài dòng) nên không thêm thư viện |
| Anthropic contextual retrieval | 2026-10-22 | Hybrid + rerank cho mức giảm lỗi lớn nhất | Giữ chuỗi sparse+dense+rerank; đo lại bằng bộ đo của dự án |
| Sentence-Transformers `CrossEncoder` / thẻ BGE reranker | 2026-10-22 | `max_length`, `batch_size`, số luồng | Áp dụng; đo trên máy này (xem báo cáo) |
| Bản ONNX int8 của cộng đồng | 2026-10-22 | Tăng tốc CPU | Không chọn (xem mục 6) |

## Hệ quả
Mọi thay đổi mã trong graph/retrieval buộc dựng lại graph và chỉ mục (phiên bản kiểm tra gắn với mã nguồn).
