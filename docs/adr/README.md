# Bản ghi Quyết định Kiến trúc (Architecture Decision Records - ADR)

Thư mục ghi nhận các quyết định kiến trúc và an toàn nền tảng của hệ thống OCOP GraphRAG:

| Mã ADR | Tiêu đề | Tóm tắt |
| :--- | :--- | :--- |
| [ADR-001](001-single-graph-output.md) | Đồ thị một đầu ra duy nhất | Hợp nhất tri thức thực thể/quan hệ về một tập đầu ra `nodes.jsonl` và `edges.jsonl`. |
| [ADR-002](002-fail-closed-citation-gate.md) | Cổng kiểm tra trích dẫn fail-closed | Bắt buộc đối soát marker `[S#]`, tọa độ `bbox` và mã `source_sha256` với tài liệu gốc. |
| [ADR-003](003-no-trust-remote-code-bge-reranker.md) | Không bật trust_remote_code | Chọn mô hình `BAAI/bge-reranker-v2-m3` ghim revision để vận hành an toàn và offline. |
| [ADR-004](004-api-based-llm-orchestration.md) | Tích hợp LLM qua API chuẩn | Kết nối Ollama/OpenAI API độc lập, hỗ trợ suy thoái mềm về chế độ chỉ trích xuất. |
| [ADR-005](005-no-unverified-score-or-star-assertions.md) | Không dùng điểm/sao chưa xác minh | Ngăn chặn việc sử dụng số liệu OCR chưa qua kiểm chứng cho đánh giá pháp lý. |
