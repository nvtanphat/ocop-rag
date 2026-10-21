# Bản ghi Quyết định Kiến trúc (Architecture Decision Records - ADR)

Thư mục ghi nhận các quyết định kiến trúc và an toàn nền tảng của hệ thống OCOP GraphRAG:

| Mã ADR | Tiêu đề | Tóm tắt |
| :--- | :--- | :--- |
| [ADR-001](001-single-graph-output.md) | Đồ thị một đầu ra duy nhất | Hợp nhất tri thức thực thể/quan hệ về một tập đầu ra `nodes.jsonl` và `edges.jsonl`. |
| [ADR-002](002-fail-closed-citation-gate.md) | Cổng kiểm tra trích dẫn fail-closed | Bắt buộc đối soát marker `[S#]`, tọa độ `bbox` và mã `source_sha256` với tài liệu gốc. |
| [ADR-003](003-no-trust-remote-code-bge-reranker.md) | Không bật trust_remote_code | Chọn mô hình `BAAI/bge-reranker-v2-m3` ghim revision để vận hành an toàn và offline. |
| [ADR-004](004-api-based-llm-orchestration.md) | Tích hợp LLM qua API chuẩn | Kết nối Ollama/OpenAI API độc lập, hỗ trợ suy thoái mềm về chế độ chỉ trích xuất. |
| [ADR-005](005-no-unverified-score-or-star-assertions.md) | Không dùng điểm/sao chưa xác minh | Ngăn chặn việc sử dụng số liệu OCR chưa qua kiểm chứng cho đánh giá pháp lý. |
| [ADR-006](006-context-window-and-parent-chain.md) | Cửa sổ trích đoạn và chuỗi cha ngắn | Excerpt theo câu hỏi từ đoạn gốc, ngữ cảnh graph ngắn, ngân sách trên toàn prompt. |
| [ADR-007](007-vocabulary-file-and-entity-catalog.md) | Từ vựng cấu hình và danh mục thực thể | Router đọc từ vựng từ tệp có schema và thực thể từ registry/graph, không literal trong mã. |
| [ADR-008](008-retrieval-budgets-and-embedding-version.md) | Ngân sách truy xuất và phiên bản nhúng | transformers>=4.57, dự phòng dense, rerank có ngân sách và cache. |
| [ADR-009](009-claim-level-answers-and-session-privacy.md) | Claim JSON, phiên, che định danh | Công bố từng claim qua cổng, phiên dùng chung, 503 có schema. |
