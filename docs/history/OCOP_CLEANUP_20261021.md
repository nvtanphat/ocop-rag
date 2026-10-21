# Báo cáo Dọn dẹp Codebase OCOP GraphRAG (2026-10-21)

## 1. Mục tiêu
Chuẩn hóa codebase theo một đường chạy mặc định tốt nhất; xóa các module/hàm/cờ thử nghiệm, debug, legacy không còn sử dụng; giữ nguyên 100% hành vi đúng hiện tại và các cổng an toàn bảo mật.

## 2. Các mục đã xóa theo nhóm

### Nhóm 1: Dead script, models và cờ debug không dùng
- **Xóa file `tools/evaluate_ocop_router.py`**: Script đánh giá synthetic router một lần, không có nơi gọi ở runtime/CLI/test (0 references).
- **Xóa class `CorpusRelease` và `RouteDecision` trong `ai_core/domain/ocop_models.py`**: Model dữ liệu cũ không có nơi nào sử dụng (`Route` trong `ai_core/orchestration/ocop/contracts.py` đang được dùng thay thế).
- **Xóa hàm `ensure_explicit_region` trong `ai_core/orchestration/ocop/semantic.py`**: Hàm rỗng không có nơi gọi (0 caller).
- **Xóa cờ/tham số `debug_candidates` trong `ai_core/orchestration/ocop/workflow.py` và `cli.py`**: Tham số thừa không có bất kỳ logic nào sử dụng.

### Nhóm 2: Đường dẫn file legacy trong builder
- **Làm sạch `ai_core/graph/ocop/builder.py`**: Loại bỏ việc tham chiếu xóa các file layout cũ không còn tạo ra (`agent_nodes.jsonl`, `agent_edges.jsonl`, `excluded_assertions.jsonl`), chỉ giữ cleanup `rejected.jsonl`.

### Nhóm 3: Dọn sạch biến và import không sử dụng (ruff F401 / F841)
- Dọn 21 unused imports (F401) và 3 unused local variables (F841) trong các module core (`dossiers.py`, `rules.py`, `shapes.py`, `evidence_grader.py`, `verification.py`, `business_candidates.py`, `structure_chunker.py`) và test files (`test_agent_planning_upgrade.py`, `test_capability_planner.py`, `test_chunking_structure.py`, `test_eval_grounding_recovery.py`, `test_ocop_router_adversarial.py`, `test_ocr_postcorrect.py`, `test_retrieval_filters.py`, `test_retrieval_integrity.py`, `test_router_adversarial.py`, `test_router_hard_cases.py`, `test_smoke_pages.py`).
- Đạt chuẩn sạch 100% `ruff check --select F`.

### Nhóm 4: Cập nhật cấu hình mặc định và tài liệu
- **Cập nhật `ai_core/orchestration/ocop/llm.py`**: Chuẩn hóa giá trị mặc định cho `OCOP_EXTRACT_LLM_WORKERS` thành 4 (khớp đường chạy chuẩn `gleanings=1, workers=4`).
- **Cập nhật `docs/SYSTEM.md`**: Đồng bộ tên mô hình reranker với `.env.example` (`Alibaba-NLP/gte-multilingual-reranker-base`).

## 3. Các mục giữ lại và lý do
- **`allow_legacy` trong `validate_graph_snapshot` (`integrity.py`, `retriever.py`)**: Giữ lại để hỗ trợ các isolated test fixtures (`test_audit_fixes.py`, `test_extraction_graph_contracts.py`) kiểm tra giải thuật traversal trên graph tổng hợp mà không cần tạo manifest hoàn chỉnh.
- **`create_debug_app` trong `backend/api/ocop_debug.py`**: Giữ lại theo yêu cầu hỗ trợ chế độ `allow_partial_debug` qua tham số tường minh.
- **Toàn bộ cổng an toàn**: Kiểm tra SHA-256 nguồn PDF, kiểm tra bbox/citation, phân tách OCR candidate và fact xác minh, kiểm tra quyền truy cập dossier, whitelist tối đa 5 tools, và review ledger.

## 4. Thống kê số dòng (diff stat)
- **Files thay đổi**: 26 files (core, tests, docs, tools).
- **Thêm**: +14 dòng.
- **Xóa**: -118 dòng.
- **Chênh lệch ròng**: Giảm 104 dòng dead code / legacy code.

## 5. Kết quả kiểm thử và so sánh E2E
- **Pytest**: 706 passed, 1 skipped (100% pass trên 707 test items).
- **Frontend build**: `vite build` thành công, 1750 modules transformed, exit code 0.
- **Ruff**: `ruff check --select F` sạch hoàn toàn (All checks passed).
- **E2E 12 câu mẫu (no-LLM)** sau khi rebuild graph/index mẫu (`build_sample.py --reindex`):
  - **Intent**: 100% khớp tuyệt đối với baseline trên toàn bộ 12 câu.
  - **Tools**: 100% khớp tuyệt đối với baseline trên toàn bộ 12 câu.
  - **Citations (nguồn, trang PDF)**: 100% khớp tuyệt đối với baseline trên toàn bộ 12 câu.
  - Trạng thái kiểm chứng: `ALL 12 QUESTIONS MATCH BASELINE PERFECTLY!`.
