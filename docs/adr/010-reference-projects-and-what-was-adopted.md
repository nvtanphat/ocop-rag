# ADR 010: Dự án tham khảo và phần được áp dụng

## Bối cảnh
Kỹ thuật cho trích xuất PDF, đồ thị tri thức, truy hồi và trả lời có trích dẫn được chọn sao cho không thêm framework không cần thiết và không viết cứng theo corpus.

## Quyết định
Chỉ áp dụng ý tưởng giải quyết một vấn đề đo được; không lấy mã nguồn và không thêm phụ thuộc.

| Dự án / tài liệu | Ý tưởng chính | Quyết định |
| --- | --- | --- |
| Docling, MinerU | Layout, thứ tự đọc, bảng nhiều trang và ô gộp | Dùng hình học PDF từ PyMuPDF; OCR cấu hình EasyOCR CRAFT + VietOCR trong `ocop_models.yaml`. Gộp rowspan/colspan và ghép chunk tiếp nối; không thêm mô hình layout thứ hai |
| Google LangExtract | Trích xuất neo vị trí nguồn, nhiều lượt (gleaning) | Mỗi thực thể/cạnh mang quote + trang + bbox + SHA-256; gleaning và vân tay trích xuất (`semantic_state`) |
| OpenSPG/KAG | Schema ràng buộc, chỉ mục hai chiều đồ thị ↔ văn bản, suy luận theo bước | `SUPPORTED_BY` nối nút ↔ EvidenceUnit, index ghi `structural_graph_version`, router lập kế hoạch nhiều công cụ. Không dùng logical-form engine |
| Microsoft GraphRAG | Tóm tắt cộng đồng cho câu hỏi tổng quát | Không dùng: corpus có sẵn cây Điều/Khoản/Điểm và phiếu; tóm tắt do LLM sinh là nội dung chưa kiểm chứng |
| LightRAG | Truy hồi hai mức (thực thể + chủ đề) | Thay bằng danh mục thực thể + facet câu hỏi + RRF; không thêm kho vector thực thể |
| RAGFlow DeepDoc | Chunk theo cấu trúc, nhãn cột bảng, xem trích dẫn trên trang gốc | Chunk cấu trúc, nhãn cột trong trích đoạn bảng, và bấm `[S#]` để xem vùng bằng chứng trên PDF khoá SHA-256 |
| Anthropic Contextual Retrieval | Ngữ cảnh ngắn đặt trước chunk; hybrid + rerank | Ngữ cảnh lấy tất định từ graph đã kiểm, không sinh bằng LLM; giữ chuỗi sparse + dense + rerank (ADR-006, ADR-008) |
| LlamaIndex (`HierarchicalNodeParser`, `SentenceWindowNodeParser`, `RouterQueryEngine`, `CitationQueryEngine`) | Tách văn bản truy xuất và hiển thị; bộ chọn trả enum hợp lệ; mỗi nhận định gắn nguồn | Áp dụng nguyên tắc: đầu ra LLM chỉ là gợi ý trong enum, citation bằng `[S#]` cùng JSON claims |
| Haystack `DocumentJoiner`, Sentence-Transformers `CrossEncoder` | BM25 + vector hợp nhất bằng RRF, rerank rồi cắt top-k | RRF tự cài, không thêm thư viện; tham số rerank theo cấu hình |
| LangGraph adaptive/corrective RAG, Self-RAG, CRAG | Phân tích câu hỏi, chấm đủ/thiếu bằng chứng | Luồng route → plan → execute → grade → recover; `missing` và kiểm độ phủ tất định, không để LLM tự chấm |
| ALCE, RAGAS, ARES | Đo citation recall/precision và faithfulness theo từng phát biểu | Đơn vị "claim"; kiểm tất định số/phủ định và xét nghĩa riêng cho diễn đạt lại. Quote đúng không tự chứng minh nội dung đúng (ADR-009) |
| Aurelio `semantic-router`, DSPy | Tuyến định nghĩa bằng câu mẫu; tối ưu định tuyến bằng số đo | Không dùng: cần embedding mỗi câu hỏi và ngưỡng chưa đo; giữ cue có kiểm soát |
| pyvi, underthesea | Tách từ tiếng Việt | Không dùng cho định tuyến: cue theo cụm từ nguyên vẹn là đủ |

## Hệ quả
Quy tắc ngôn ngữ nằm trong `configs/ocop_language.yaml` và mã chung; `tests/ocop/contracts/test_no_corpus_literals.py` giữ cho mã không chứa hằng số theo corpus. Dependency UI/test được khai báo trong package frontend; ADR này không cấm công cụ kiểm thử cần thiết.

Điều kiện cạnh `RESPONSIBLE_FOR`: mục `b)` chỉ thừa hưởng tiêu đề danh sách, không thừa hưởng điều kiện của mục `a)` anh em. Review rebuild, làm mới index và build corpus dùng chung khóa `.system.lock`.
