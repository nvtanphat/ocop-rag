# ADR 010: Dự án tham khảo và phần được áp dụng

## Bối cảnh
Cần chọn kỹ thuật cho trích xuất PDF, đồ thị tri thức và truy hồi mà không thêm framework không cần thiết và không hardcode theo corpus.

## Quyết định
Chỉ áp dụng ý tưởng giải quyết lỗi đã đo được; không thêm phụ thuộc mới.

| Dự án (đọc 2026-10-22) | Ý tưởng chính | Quyết định |
| --- | --- | --- |
| Docling, MinerU | Layout + thứ tự đọc + bảng nhiều trang, bảng gộp ô | Giữ PyMuPDF + PaddleOCR layout hiện có; đã có gộp rowspan/colspan, ghép chunk tiếp nối và khôi phục khoảng trắng từ hình học PDF. Không thêm mô hình layout thứ hai |
| Google LangExtract | Trích xuất có neo vị trí nguồn, nhiều lượt (gleaning) | Đã tương đương: mỗi thực thể/cạnh mang quote + trang + bbox + SHA-256; gleaning và vân tay trích xuất (`semantic_state`) |
| OpenSPG/KAG | Schema ràng buộc, chỉ mục hai chiều đồ thị ↔ văn bản, suy luận theo bước | Đã áp dụng: `SUPPORTED_BY` nối nút↔EvidenceUnit, index ghi `structural_graph_version`; router chọn nhiều công cụ có kế hoạch. Không dùng logical-form engine |
| Microsoft GraphRAG | Tóm tắt cộng đồng cho câu hỏi tổng quát | Không áp dụng: corpus nhỏ, có sẵn cây Điều/Khoản/Điểm và phiếu; tóm tắt do LLM sinh sẽ tạo nội dung chưa kiểm chứng |
| LightRAG | Truy hồi hai mức (thực thể + chủ đề) | Tương đương bằng danh mục thực thể + facet câu hỏi + RRF; không thêm kho vector thực thể |
| RAGFlow | Hiểu tài liệu theo mẫu, xem trích dẫn trên trang gốc | Áp dụng phần xem trích dẫn: bấm `[S#]` hiện vùng bằng chứng trên PDF khóa SHA-256 |

## Hệ quả
Quy tắc ngôn ngữ nằm trong `configs/ocop_language.yaml` và mã chung; `tests/ocop/contracts/test_no_corpus_literals.py` giữ cho mã không chứa hằng số theo corpus. Dependency UI/test được khai báo trong package frontend; ADR này không cấm công cụ kiểm thử cần thiết.
Điều kiện cạnh `RESPONSIBLE_FOR`: mục `b)` chỉ thừa hưởng tiêu đề danh sách, không thừa hưởng điều kiện của mục `a)` anh em.
Review rebuild, làm mới index và build corpus dùng chung khóa `.system.lock`.
