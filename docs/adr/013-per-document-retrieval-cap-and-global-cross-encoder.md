# ADR 013: Giới hạn số đoạn mỗi văn bản và rerank cross-encoder toàn cục sau hợp nhất

Trạng thái: **Accepted**. Cài đặt: `ai_core/retrieval/ocop/search.py`, `ai_core/orchestration/ocop/answer.py`, `ai_core/orchestration/ocop/workflow.py`, `configs/ocop_retrieval.yaml`.

## Bối cảnh

Khâu truy xuất và hợp nhất bằng chứng có hai hạn chế:

1. **Một văn bản ngắn chiếm trọn danh sách kết quả**: Các câu hỏi về một địa phương hoặc chủ đề cụ thể thường làm một văn bản hướng dẫn địa phương (hoặc quyết định cũ cùng tên) khớp ở tất cả các trang. Khi `search` lấy `top_k` (mặc định 8) theo điểm thuần túy, toàn bộ 8 vị trí bị lấp đầy bởi cùng một văn bản nguồn, đẩy các đoạn chứa câu trả lời ở các văn bản quy chuẩn khác ra ngoài.
2. **Hợp nhất đa công cụ (tool fusion) bị hòa điểm đầu**: Khi người dùng hỏi câu hỏi phức hợp, Planner kích hoạt nhiều công cụ (`search_regulations`, `lookup_product_subgroup`, `lookup_recognition`, `search_graph`). Thuật toán RRF (Reciprocal Rank Fusion) trên các bảng xếp hạng công cụ gán điểm cho vị trí thứ nhất của mọi công cụ bằng nhau (1 / (60 + 1)). Kết quả là một dòng tiêu đề nhóm sản phẩm từ lookup bảng có thể đứng trước một đoạn văn bản quy định mà bộ tìm kiếm văn bản xếp hạng 1, đẩy thông tin cốt lõi xuống dưới.

Dự án tham khảo là ViCAS-RAG:
- Mục 2.3: `diversify_hits` giới hạn số lượt trúng của mỗi tài liệu để bảo đảm tính đa dạng nguồn.
- Mục 2.4: Sau khi hợp nhất các danh sách bằng chứng từ các công cụ/nhánh khác nhau, dùng mô hình cross-encoder toàn cục để chấm lại và phá vỡ thế hòa điểm ở phần đầu danh sách.

## Quyết định

1. **Giới hạn số đoạn mỗi văn bản (`max_hits_per_document`)**:
   - Thêm tham số `retrieval.max_hits_per_document` vào `configs/ocop_retrieval.yaml` (giá trị mặc định là 3), kiểm tra giá trị qua `ai_core/retrieval/ocop/settings.py`.
   - Trong `ai_core/retrieval/ocop/search.py`, mỗi văn bản (`source_id`) chỉ được giữ tối đa `max_hits_per_document` đoạn ở danh sách ưu tiên (`first`). Các đoạn vượt trần được gom vào danh sách phần dư (`later`). Kết quả cuối cùng là `(first + later)[:top_k]`.
   - Tham số `top_k` trong các hàm gọi `search` tại `ai_core/orchestration/ocop/tools.py` được đọc từ cấu hình `retrieval.top_k`.

2. **Chấm lại bằng cross-encoder sau hợp nhất đa công cụ (`rerank_fused`)**:
   - Khi cờ `rerank=True` (chế độ hybrid có bật rerank), hàm `ai_core/orchestration/ocop/answer.py:rerank_fused` lấy phần đầu các hàng bằng chứng đã hợp nhất (`head = rows[:24]`), gọi cross-encoder cục bộ (`BAAI/bge-reranker-v2-m3`) chấm lại theo câu hỏi.
   - Hợp nhất thứ tự ban đầu và thứ tự cross-encoder bằng RRF với trọng số cân bằng. Khi hòa điểm, thứ tự của cross-encoder được ưu tiên.
   - Các hàng còn lại sau 24 hàng đầu giữ nguyên thứ tự RRF ban đầu.

## Hệ quả

- Văn bản quy chuẩn chứa câu trả lời không còn bị một văn bản khớp ở mọi trang đẩy khỏi `top_k`.
- Cross-encoder phân định thế hòa ở đầu danh sách hợp nhất, nên đoạn quy định mà bộ tìm văn bản xếp đầu đứng trên dòng tiêu đề từ lookup bảng.
- Chi phí: mỗi câu thêm một lượt cross-encoder trên tối đa 24 hàng.

## Phương án đã cân nhắc

- **Thêm trang liền kề các kết quả tốt nhất (theo vn-legal-rag)**:
  - Ý tưởng: với mỗi đoạn trúng tuyển ở top đầu, tự động kéo thêm đoạn của trang trước và trang sau trong cùng văn bản để tránh mất ngữ cảnh liên trang.
  - Trộn các trang liền kề vào RRF làm loãng điểm của đoạn cốt lõi và giảm top-1 trên bộ truy xuất; nối chúng vào cuối ngữ cảnh không giúp mô hình trả lời. Phương án này bị loại.
- **Dùng cross-encoder cho toàn bộ hàng thay vì chỉ 24 hàng đầu**:
  - Khi danh sách hợp nhất từ 4 công cụ có thể lên tới 40-60 hàng, chấm toàn bộ tốn thêm hơn 20 giây mỗi câu trên CPU mà không làm tăng Recall@3 hay MRR. Giới hạn 24 hàng đầu cân bằng giữa độ chính xác và độ trễ.
