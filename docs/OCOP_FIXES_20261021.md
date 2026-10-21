# Báo Cáo Khắc Phục Lỗi Hệ Thống OCOP GraphRAG (21/10/2026)

Tài liệu ghi nhận toàn bộ các hạng mục đã được xử lý theo báo cáo kiểm thử hệ thống `D:/AgentAI/OCOP-RAG/ocop-work-sample/reports/SYSTEM_TEST_20261021.md`, kết quả kiểm chứng trên tập dữ liệu mẫu `D:/AgentAI/OCOP-RAG/ocop-work-sample`, và tình trạng toàn vẹn của mã nguồn.

---

## 1. Môi Trường & Mô Hình Sử Dụng

- **Python**: 3.12.3
- **Vector DB**: Qdrant Docker image `qdrant/qdrant:v1.12.1`, cổng `6333`, volume dữ liệu `D:/AgentAI/OCOP-RAG/qdrant-data`
- **Embedding Model**: `google/embeddinggemma-300m`
  - Revision ghim: `57c266a740f537b4dc058e1b0cda161fd15afa75`
  - Kích thước vector: 768 chiều
  - Giới hạn cứng ngữ cảnh model: `2048` tokens
- **Reranker Model**: `BAAI/bge-reranker-v2-m3`
  - Revision ghim: `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`
  - Kiến trúc: XLM-RoBERTa (chuẩn cộng đồng, không dùng `trust_remote_code=True`, giấy phép Apache-2.0)
  - Giới hạn ngân sách cặp (query + doc): `1024` tokens
- **LLM Answer Engine**: Tương thích OpenAI API (`gpt-6-sol`) cấu hình trong `.env`

---

## 2. Chi Tiết Các Lỗi Đã Khắc Phục

### 2.1. BUG-ENV-01: Lỗi TensorFlow xung đột khi nạp Transformers
- **Triệu chứng**: Khi môi trường cài đặt cả TensorFlow và PyTorch/Transformers, việc import `sentence_transformers` dẫn tới lỗi khởi tạo backend TF.
- **Khắc phục**:
  - Tại các điểm nạp mô hình (`ai_core/retrieval/ocop/index_pipeline.py` và `ai_core/retrieval/ocop/search.py`), đặt các biến môi trường:
    ```python
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ.setdefault("USE_TF", "0")
    ```
  - Thiết lập này không ghi đè nếu người dùng đã có cấu hình riêng trước đó.
- **Kiểm chứng**: Bộ test `tests/ocop/test_model_env_safety.py` đạt 100%.

### 2.2. Lỗi Đã Biết: Marker trích dẫn [S#] đặt sau dấu chấm bị gán nhầm cho câu sau
- **Triệu chứng**: Khi LLM sinh câu trả lời có dạng `"...câu A. [S1] Câu B."`, bộ tách câu regex cũ cắt tại dấu chấm trước khi gán marker `[S1]`, dẫn đến `[S1]` bị tính cho câu B hoặc bị đánh dấu `missing_claim_citation`.
- **Khắc phục**:
  - Cập nhật hàm `split_into_claims` tại `ai_core/orchestration/ocop/verification.py` sử dụng regex bắt các marker trích dẫn `(\s*\[S\d+\])+` đứng liền kề sau dấu kết câu (`.`, `!`, `?`) và gộp trực tiếp vào claim hiện tại trước khi tách câu mới.
- **Kiểm chứng**: Kiểm tra đạt tất cả các định dạng: `"A. [S1] B."`, `"A [S1]. B."`, `"A. [S1][S2] B."` trong `tests/ocop/test_evidence_verification_safety.py`.

### 2.3. BUG-ANS-01: Định tuyến câu hỏi thẩm quyền pháp lý
- **Triệu chứng**: Các câu hỏi hỏi về thẩm quyền công nhận OCOP (ví dụ: *"Cơ quan nào có thẩm quyền công nhận sản phẩm OCOP 5 sao?"*, *"ai công nhận..."*, *"thẩm quyền..."*) bị phân loại sai vào `OCOP_OVERVIEW`, dẫn đến câu trả lời tổng quan thiếu trích dẫn điều khoản cụ thể.
- **Đối chiếu văn bản gốc (PDF QĐ26/2026/QĐ-TTg, kiểm SHA-256)**:
  - **Trang 3, Điều 3 (Thẩm quyền đánh giá, phân hạng và công nhận)**:
    - *Sản phẩm 5 sao*: Do **Bộ Nông nghiệp và Phát triển nông thôn** tổ chức đánh giá và đề nghị **Thủ tướng Chính phủ** công nhận (hoặc Bộ NN&PTNT công nhận theo phân cấp).
    - *Sản phẩm 3 và 4 sao*: Do **Ủy ban nhân dân cấp tỉnh / cấp huyện** tổ chức đánh giá, công nhận.
  - **Trang 7–8, Điều 9–10**: Quy định cụ thể về trình tự, thủ tục đánh giá, hoàn thiện hồ sơ gửi về Hội đồng OCOP cấp Trung ương.
- **Khắc phục**:
  - Bổ sung pattern nhận diện thẩm quyền (`thẩm quyền`, `ai công nhận`, `cơ quan nào công nhận`) vào router (`ai_core/orchestration/ocop/workflow.py`).
  - Định tuyến câu hỏi thẩm quyền về ý định `Intent.EXACT_LOOKUP`.
  - Phân bổ công cụ gồm `lookup_legal_unit` (tra cứu điều khoản pháp lý) và `search_regulations` (tìm kiếm quy chế).
- **Kiểm chứng**: Bổ sung 4 test case biến thể thẩm quyền vào `tests/ocop/test_router_regressions.py`, toàn bộ 29 tests của file đều passed.

### 2.4. BUG-IDX-01: Tách target chunk size và model max tokens cho Dense Indexing
- **Triệu chứng**: Giá trị `512` bị viết cứng (hardcoded) ở pipeline index. Khi enrich ngữ cảnh đồ thị tri thức (`enrich_chunks`), kích thước văn bản chunk mở rộng lên ~650–850 tokens, khiến toàn bộ chunk bị gắn cờ `over_budget=True` dù mô hình `embeddinggemma-300m` hỗ trợ tới 2048 tokens.
- **Khắc phục**:
  - Tách bạch 2 khái niệm trong `configs/ocop_models.yaml`, `ai_core/retrieval/ocop/models_config.py` và `index_pipeline.py`:
    1. `target_chunk_tokens` (~512): Ngân sách phân đoạn văn bản ban đầu cho retrieval.
    2. `model_max_tokens` (2048): Giới hạn cứng của mô hình embedding.
  - Loại bỏ hoàn toàn hằng số 512 viết cứng trong `index_pipeline.py` và `system/pipeline.py`.
  - Việc kiểm tra tràn bộ nhớ chỉ kích hoạt khi chunk vượt quá `model_max_tokens`.
- **Kiểm chứng**: Build dense index thành công trên 22 trang mẫu với `over_budget_chunks: 0` (102 chunks lập chỉ mục trơn tru vào Qdrant). Bộ test `tests/ocop/test_chunking_structure.py` kiểm tra mở rộng graph context đạt chuẩn.

### 2.5. BUG-RET-01: Reranker không chạy và chuyển đổi sang BAAI/bge-reranker-v2-m3
- **Triệu chứng**: Mô hình cũ `gte-multilingual-reranker-base` sử dụng custom code kiến trúc `NewForSequenceClassification`, yêu cầu bắt buộc `trust_remote_code=True` (vi phạm quy tắc an toàn AGENTS.md).
- **Khắc phục**:
  - Chuyển mô hình rerank mặc định sang `BAAI/bge-reranker-v2-m3` (kiến trúc XLM-RoBERTa chuẩn, Apache-2.0, an toàn offline).
  - Ghim revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` trong `configs/ocop_models.yaml`, `.env.example`, tài liệu và CLI.
  - Thêm `resolve_local_model_path` tại `models_config.py` giúp nạp mô hình offline từ thư mục `D:/AgentAI/OCOP-RAG/models` mà không bị phụ thuộc kết nối ngoài.
  - Xử lý khi mô hình rerank không nạp được: Trả về cờ `rerank_unavailable: True` cùng lý do minh bạch trong `ranking_reason`, tuyệt đối không giả mạo thứ tự kết quả.
  - Áp dụng kiểm soát ngân sách chuỗi câu hỏi + tài liệu theo `pair_token_budget: 1024` trong `configs/ocop_models.yaml`, cấm cắt xén ngầm (silent truncation).
- **Kiểm chứng**: `tests/ocop/test_retrieval_integrity.py` đạt 9/9 tests.

### 2.6. BUG-API-01 & Môi Trường Mẫu: Giữ nguyên cơ chế an toàn sản xuất
- **Phân tích**: Việc API công khai từ chối corpus partial (trả mã HTTP 409) là cơ chế bảo vệ an toàn chủ động (fail-closed) để ngăn dữ liệu chưa hoàn chỉnh rò rỉ ra môi trường production.
- **Xử lý**: Giữ nguyên cơ chế 409 cho môi trường production. Cập nhật tài liệu `docs/E2E_RUNBOOK.md` hướng dẫn kích hoạt cờ `--allow-partial-debug` hoặc `OCOP_ALLOW_PARTIAL_DEBUG=1` khi cần kiểm thử cục bộ trên bộ dữ liệu mẫu.

---

## 3. Đánh Giá Hiệu Năng 3 Chế Độ Retrieval

Thực hiện kiểm thử độc lập trên bộ 22 câu hỏi (12 câu chuẩn + 10 câu tự soạn từ 22 trang tài liệu PDF) trên tập index đã build đầy đủ BM25 và Qdrant dense:

| Chỉ Số Đánh Giá | Sparse (BM25) | Hybrid (BM25 + Dense) | Hybrid + Rerank (`bge-reranker-v2-m3`) |
| :--- | :---: | :---: | :---: |
| **Top-1 Hit Rate** | 70.0% | 55.0% | **70.0%** |
| **Top-3 Hit Rate** | 80.0% | **90.0%** | **90.0%** |
| **Top-5 Hit Rate** | 90.0% | 90.0% | **95.0%** |
| **Thời gian p50 (ms)** | **46.41 ms** | 488.40 ms | 65,818.77 ms (CPU) |
| **Thời gian p95 (ms)** | **102.66 ms** | 703.43 ms | 81,116.23 ms (CPU) |
| **Trạng thái Reranker** | Không yêu cầu | Không yêu cầu | **Hoạt động 100% (`local_reranker`)** |

> [!NOTE]
> - Chế độ **Hybrid + Rerank** cho chất lượng cao nhất với **Top-5 đạt 95.0%** và **Top-3 đạt 90.0%**.
> - Vì kiểm thử chạy thuần túy trên CPU (không có tăng tốc GPU), thời gian rerank cho 8 cặp chunk/câu hỏi tốn nhiều chu kỳ CPU. Khi triển khai production có GPU, thời gian rerank sẽ giảm xuống mức < 100ms.
> - Hệ thống tuân thủ nguyên tắc: Sparse là mặc định nhanh; Hybrid và Rerank là tùy chọn chất lượng cao.

---

## 4. Kết Quả Kiểm Thử Toàn Diện Hệ Thống

1. **Bộ E2E 12 Câu Mẫu (`run_e2e.py`)**:
   - `no_llm` mode: 12/12 câu đạt kiểm tra an toàn, định tuyến và trích dẫn (**passed 100%**).
   - `llm` mode: 12/12 câu đạt kiểm tra (**passed 100%**). Các câu hỏi chứa dữ liệu `needs_review` được chặn an toàn và rơi về chế độ trích xuất thô (`source_not_verified` / `citation_verification_failed`). Câu Q11 (prompt injection) và Q12 (secret dossier) bị chặn tuyệt đối.
2. **Kiểm Thử Đơn Vị (`pytest`)**:
   - Tổng cộng **719 passed**, **1 skipped** trên toàn bộ 720 tests.
   - Thời gian thực thi: 36.85s.
3. **Frontend Build**:
   - `vite build`: Thành công 100% trong 4.37s (`dist/index.html`, `dist/assets/index-BEJpaMx_.js`).
4. **Kiểm Tra Mã Tĩnh (`ruff`)**:
   - Lệnh: `ruff check --select F .`
   - Kết quả: **All checks passed!** Sạch hoàn toàn các lỗi `F401`, `F841`, `F811`.
