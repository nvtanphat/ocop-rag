# Retrieval — 2026-10-21

Mẫu debug bền ngoài repo: `D:/AgentAI/OCOP-RAG/ocop-work-sample` (22 trang OCR 300 DPI:
QĐ26 p1–8, 13, 17–19, 28–30; QĐ1489 p1; QĐ525 p1, 3; Thành Sen p1–4). Chế độ
`allow_partial_debug`, không giả manifest complete. Graph 703/1349, rejected=0; index 102 chunk.

## Thay đổi

- **Nguồn cấu trúc duy nhất:** `lookup_*` đọc graph đã lọc `check` (passed/human_verified);
  bỏ đường đọc `*_candidates` trong runtime.
- **Chunk theo cấu trúc:** ngữ cảnh tiêu chí cha từ graph, kể cả bảng nối trang (`graph_context.py`).
- **BM25:** chuẩn hóa dấu, nhận mã tiêu chí/mẫu.
- **Fusion** (`fusion.py`): ngân sách excerpt theo token thay cho giới hạn 4. Xoay vòng evidence
  cho từng vế của câu hỏi, gồm vế theo mã ("1.6", "Mẫu 02") và vế diễn đạt tự nhiên (tách tại
  `;`, `?`, ", và", "đồng thời"). Chỉ vế theo mã là bắt buộc; vế tự nhiên thiếu evidence được báo
  trong `uncovered_question_parts`, không chặn câu trả lời.
- **Router:** câu hỏi chủ thể sản xuất ("chủ thể nào", "chủ thể của", "ai sản xuất"…) vào
  `RECOGNITION_LOOKUP`. Tên sản phẩm cắt tại "do/bởi"; tên cụ thể không bị thu về danh mục chung.
- **Seed graph:** thêm Product khớp tên sản phẩm mà người dùng viết nguyên văn trong câu hỏi.
  Slot không xuất hiện trong câu hỏi thì không dùng làm alias.

## 12 câu E2E, chế độ không LLM (đối chiếu crop PDF đã kiểm SHA)

| # | Trước (6c38f2e) | Sau |
|---|---|---|
| 1 HANA do chủ thể nào sản xuất | OCOP_OVERVIEW, chỉ BM25 | RECOGNITION_LOOKUP; HTX Thụy Hương (QĐ525 p3) |
| 2 Phiếu 3 mục 1.6 + ghi chú 1.1 | thiếu vế | đủ: hồ sơ môi trường p28, thu gom xử lý chất thải và bao gói thân thiện p29, yêu cầu 100% p28 |
| 3–7, 9, 10, 12 | đạt | đạt, không đổi |
| 8 Chủ thể HANA → quyết định | OWNED_BY đứng đầu | OWNED_BY đứng đầu (đã sửa hồi quy seed trong lượt này) |
| 11 Injection + REPLACES | đạt | đạt (đã sửa hồi quy fusion trong lượt này) |

Cả 24 lượt (12 câu × không LLM/LLM) đạt kiểm tra cấu trúc: ≤5 tool đã đăng ký, `[S#]` hợp lệ,
SHA và bbox đúng, câu 10/12 không trích dẫn. Test: 706 passed, 1 skipped; frontend build đạt.

## Hạn chế cho Phase 3

- Chế độ LLM (Ollama qwen3.5:2b): mọi câu bị cổng citation chặn (`citation_verification_failed`),
  như trước. Model thiếu `[S#]` theo từng claim, thêm kết luận ngoài câu hỏi và nêu điểm/sao.
- Chưa đo source-hit/page-hit: evaluator cần corpus đầy đủ ở trạng thái ready.
- Dense/rerank chưa chạy trên mẫu (model không có sẵn local; không tự tải).
- OCR sai giữ nguyên (ví dụ Phụ lục III đọc thành II ở QĐ26 p4).
