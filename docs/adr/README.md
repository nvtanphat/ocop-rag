# Bản ghi Quyết định Kiến trúc (Architecture Decision Records - ADR)

Thư mục ghi nhận các quyết định kiến trúc và an toàn nền tảng của hệ thống OCOP GraphRAG:

| Mã ADR | Tiêu đề | Tóm tắt |
| :--- | :--- | :--- |
| [ADR-001](001-single-graph-output.md) | Đồ thị một đầu ra duy nhất | Hợp nhất tri thức thực thể/quan hệ về một tập đầu ra `nodes.jsonl` và `edges.jsonl`. |
| [ADR-002](002-fail-closed-citation-gate.md) | Cổng kiểm tra trích dẫn fail-closed | Bắt buộc đối soát marker `[S#]`, tọa độ `bbox` và mã `source_sha256` với tài liệu gốc. |
| [ADR-003](003-no-trust-remote-code-bge-reranker.md) | Không bật trust_remote_code | Chọn mô hình `BAAI/bge-reranker-v2-m3` ghim revision để vận hành an toàn và offline. |
| [ADR-004](004-api-based-llm-orchestration.md) | Tích hợp LLM qua API chuẩn | Kết nối API tương thích OpenAI độc lập, hỗ trợ suy thoái mềm về chế độ chỉ trích xuất. |
| [ADR-005](005-no-unverified-score-or-star-assertions.md) | Không dùng điểm/sao chưa xác minh | Ngăn chặn việc sử dụng số liệu OCR chưa qua kiểm chứng cho đánh giá pháp lý. |
| [ADR-006](006-context-window-and-parent-chain.md) | Cửa sổ trích đoạn và chuỗi cha ngắn | Excerpt theo câu hỏi từ đoạn gốc, ngữ cảnh graph ngắn, ngân sách trên toàn prompt. |
| [ADR-007](007-vocabulary-file-and-entity-catalog.md) | Từ vựng cấu hình và danh mục thực thể | Router đọc từ vựng từ tệp có schema và thực thể từ registry/graph, không literal trong mã. |
| [ADR-008](008-retrieval-budgets-and-embedding-version.md) | Ngân sách truy xuất và phiên bản nhúng | transformers>=4.57, dự phòng dense, rerank có ngân sách và cache. |
| [ADR-009](009-claim-level-answers-and-session-privacy.md) | Claim JSON, phiên, che định danh | Công bố từng claim qua cổng, phiên dùng chung, 503 có schema. |
| [ADR-010](010-reference-projects-and-what-was-adopted.md) | Dự án tham khảo và phần áp dụng | Docling, MinerU, LangExtract, KAG, GraphRAG, LightRAG, RAGFlow, LlamaIndex: chỉ lấy ý tưởng đo được, không thêm phụ thuộc. |
| [ADR-011](011-first-class-norms-and-concept-identity.md) | Quy phạm và danh tính khái niệm | Quy phạm có kiểu, đề xuất có provenance, duyệt theo lô, seed kép và graph-only publication có kiểm tương thích chỉ mục. |
| [ADR-012](012-simple-graph-roles-like-vicas.md) | Schema graph gọn theo vai trò | 14 vai trò nút và 19 vai trò quan hệ ánh xạ từ loại hiện có, nguồn gốc ghi phẳng, không đổi ID hay dấu vân tay. |
| [ADR-013](013-per-document-retrieval-cap-and-global-cross-encoder.md) | Giới hạn đoạn mỗi văn bản và rerank toàn cục | Giới hạn tối đa 3 đoạn mỗi văn bản trong tìm kiếm (ViCAS diversify_hits) và rerank cross-encoder phá vỡ hòa điểm RRF sau hợp nhất công cụ. |
| [ADR-014](014-model-based-followup-rewrite.md) | Viết lại câu nối tiếp bằng mô hình | Mô hình viết lại câu trỏ ngược từ 3 câu gần nhất theo ViCAS-RAG/Legal-RAG; kiểm tra số và tên riêng không vượt hội thoại, tối đa 2 từ thường mới. |
