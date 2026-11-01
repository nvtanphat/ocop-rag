# ADR 013: Giới hạn số đoạn mỗi văn bản và rerank cross-encoder toàn cục sau hợp nhất

Trạng thái: **Accepted**. Cài đặt: `ai_core/retrieval/ocop/search.py`, `ai_core/orchestration/ocop/answer.py`, `ai_core/orchestration/ocop/workflow.py`, `configs/ocop_retrieval.yaml`.

## Bối cảnh

Trong đợt cải thiện truy xuất ngày 2026-11-01, hệ thống gặp hai hạn chế trong khâu truy xuất và hợp nhất bằng chứng:

1. **Một văn bản ngắn chiếm trọn danh sách kết quả**: Các câu hỏi về một địa phương hoặc chủ đề cụ thể thường làm một văn bản hướng dẫn địa phương (hoặc quyết định cũ cùng tên) khớp ở tất cả các trang. Khi `search` lấy `top_k` (mặc định 8) theo điểm thuần túy, toàn bộ 8 vị trí bị lấp đầy bởi cùng một văn bản nguồn, đẩy các đoạn chứa câu trả lời ở các văn bản quy chuẩn khác ra ngoài.
2. **Hợp nhất đa công cụ (tool fusion) bị hòa điểm đầu**: Khi người dùng hỏi câu hỏi phức hợp, Planner kích hoạt nhiều công cụ (`search_regulations`, `lookup_product_subgroup`, `lookup_recognition`, `search_graph`). Thuật toán RRF (Reciprocal Rank Fusion) trên các bảng xếp hạng công cụ gán điểm cho vị trí thứ nhất của mọi công cụ bằng nhau (1 / (60 + 1)). Kết quả là một dòng tiêu đề nhóm sản phẩm từ lookup bảng có thể đứng trước một đoạn văn bản quy định mà bộ tìm kiếm văn bản xếp hạng 1, đẩy thông tin cốt lõi xuống dưới.

Dự án tham khảo là ViCAS-RAG:
- Mục 2.3: `diversify_hits` giới hạn số lượt trúng của mỗi tài liệu để bảo đảm tính đa dạng nguồn.
- Mục 2.4: Sau khi hợp nhất các danh sách bằng chứng từ các công cụ/nhánh khác nhau, dùng mô hình cross-encoder toàn cục để chấm lại và phá vỡ thế hòa điểm ở phần đầu danh sách.

## Quyết định

1. **Giới hạn số đoạn mỗi văn bản (`max_hits_per_document`)**:
   - Thêm tham số `retrieval.max_hits_per_document` vào `configs/ocop_retrieval.yaml` (giá trị mặc định là 3), kiểm tra giá trị qua `ai_core/retrieval/ocop/settings.py`.
   - Trong `ai_core/retrieval/ocop/search.py`, mỗi văn bản (`source_id`) chỉ được giữ tối đa `max_hits_per_document` đoạn ở danh sách ưu tiên (`first`). Các đoạn vượt trần được gom vào danh sách phần dư (`later`). Kết quả cuối cùng là `(first + later)[:top_k]`.
   - Tham số `top_k` trong các hàm gọi `search` tại `ai_core/orchestration/ocop/tools.py` được đọc từ cấu hình `retrieval.top_k` thay vì đặt số cứng 8.

2. **Chấm lại bằng cross-encoder sau hợp nhất đa công cụ (`rerank_fused`)**:
   - Khi cờ `rerank=True` (chế độ hybrid có bật rerank), hàm `ai_core/orchestration/ocop/answer.py:rerank_fused` lấy phần đầu các hàng bằng chứng đã hợp nhất (`head = rows[:24]`), gọi cross-encoder cục bộ (`BAAI/bge-reranker-v2-m3`) chấm lại theo câu hỏi.
   - Hợp nhất thứ tự ban đầu và thứ tự cross-encoder bằng RRF với trọng số cân bằng. Khi hòa điểm, thứ tự của cross-encoder được ưu tiên.
   - Các hàng còn lại sau 24 hàng đầu giữ nguyên thứ tự RRF ban đầu.

## Hệ quả

Đo lường ngày 2026-11-01 trên bộ dữ liệu `data/evaluations/ocop/ocop_retrieval_gold_100_natural_final.json` (dataset_version `1.2.1-natural-query`, 100 câu) và `data/evaluations/ocop/ocop_graphrag_multihop_gold_25.json` (25 câu, 64 bước):

- Giới hạn 3 đoạn mỗi văn bản (commit `ec73930`): multihop MH013 tăng 2 bước thành công (trang 3 của QĐ26 lọt vào top khi QĐ148 và QĐ1489 không còn chiếm hết 8 chỗ); 5 câu hỏi kết hợp ngẫu nhiên giữ nguyên kết quả và thời gian chạy.
- Cross-encoder sau hợp nhất công cụ (commit `7d29544`, `5b9558f`):
  - Truy xuất đơn bước (100 câu): top-1 đạt từ 59 lên 65, MRR từ 0,721 lên 0,777, Recall@3 từ 0,74 lên 0,83.
  - Multihop (25 câu): số bước tìm đúng trang tăng từ 52/64 lên 53/64, số chuỗi tìm đủ mọi bước tăng từ 16 lên 17 chuỗi.
  - Chi phí: thời gian xử lý tăng thêm khoảng 8 giây/câu trên CPU khi chạy qua cross-encoder.

## Phương án đã cân nhắc

- **Thêm trang liền kề các kết quả tốt nhất (theo vn-legal-rag)**:
  - Ý tưởng: với mỗi đoạn trúng tuyển ở top đầu, tự động kéo thêm đoạn của trang trước và trang sau trong cùng văn bản để tránh mất ngữ cảnh liên trang.
  - Kết quả thử nghiệm: khi trộn các trang liền kề vào RRF, độ chính xác top-1 giảm từ 61 xuống 54 do các trang lân cận gây loãng điểm của đoạn cốt lõi; khi nối các trang này vào cuối danh sách ngữ cảnh thì không mang lại lợi ích cho việc trả lời của mô hình. Phương án này bị loại bỏ.
- **Dùng cross-encoder cho toàn bộ hàng thay vì chỉ 24 hàng đầu**:
  - Khi danh sách hợp nhất từ 4 công cụ có thể lên tới 40-60 hàng, chấm toàn bộ tốn thêm hơn 20 giây mỗi câu trên CPU mà không làm tăng Recall@3 hay MRR. Giới hạn 24 hàng đầu cân bằng giữa độ chính xác và độ trễ.
