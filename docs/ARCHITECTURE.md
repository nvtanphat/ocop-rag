# Kiến trúc Hệ thống OCOP GraphRAG (System Architecture)

Tài liệu mô tả luồng dữ liệu từ PDF nguồn đến câu trả lời có trích dẫn đã kiểm chứng và vị trí mã nguồn tương ứng của từng tầng.

---

## 1. Luồng Xử lý Dữ liệu Toàn trình (End-to-End Pipeline Flow)

```
[PDF Gốc (data/raw/ocop)]
       │
       ▼ (1. Khóa băm SHA-256: configs/ocop_sources.lock.json)
[Bộ nạp & OCR Cục bộ: EasyOCR CRAFT + VietOCR VGG Transformer]
       │
       ▼ (2. Phân đoạn hình học, nhận dạng bảng)
[Đơn vị Bằng chứng (EvidenceUnit): bbox, pdf_page, source_sha256]
       │
       ▼ (3. Trích xuất tất định + Đề xuất LLM căn cứ vào trích đoạn)
[Tri thức Thực thể & Quan hệ (Legal Structure, Criteria, Procedures, Recognitions)]
       │
       ▼ (4. Đồ thị một đầu ra duy nhất: data/processed/ocop/graph/)
[Đồ thị Tri thức Chuẩn hóa: nodes.jsonl, edges.jsonl (check, origin)]
       │
       ▼ (5. Phân mảnh theo cấu trúc & Lập chỉ mục)
[Chỉ mục Tìm kiếm: Chunks + BM25 Lexical + Qdrant Dense Vectors]
       │
       ▼ (6. Phân luồng câu hỏi & Kế hoạch gọi công cụ (Tối đa 5 tools))
[Router & Tool Planner: search_regulations, lookup_legal_unit, v.v.]
       │
       ▼ (7. Truy xuất & Hợp nhất: Sparse / Hybrid RRF / BGE-Reranker-v2-m3)
[Bằng chứng Đối soát được xếp hạng]
       │
       ▼ (8. Tầng sinh câu trả lời & Cổng trích dẫn Fail-Closed: [S#] Gate)
[Câu trả lời có căn cứ pháp lý & Trích dẫn tọa độ PDF]
       │
       ▼ (9. API RESTful: /api/ocop/*)
[Giao diện Người dùng: React / Vite UI & Review Ledger]
```

---

## 2. Chi tiết Các Tầng Xử lý

### Tầng 1: Nguồn dữ liệu & Tiền xử lý PDF (Ingestion & OCR)
* **Nguyên tắc**: Byte PDF gốc tại `data/raw/ocop` là bất biến. Danh mục nguồn được khai báo tại `configs/ocop_sources.json` và khóa băm tại `configs/ocop_sources.lock.json`.
* **Cơ chế**: Trang PDF dạng text gốc được trích xuất trực tiếp qua PyMuPDF; trang scan được đưa qua pipeline: khử nghiêng (`raster_preprocess.py`) → phát hiện khối chữ bằng EasyOCR CRAFT → nhận dạng ký tự tiếng Việt bằng VietOCR VGG Transformer (`easy_viet_ocr.py`).
* **Bảng biểu**: Module `table_parser.py` và `table_continuity.py` khôi phục bảng đa dòng, ghép nối bảng xuyên trang và lưu trữ tọa độ từng ô.

### Tầng 2: Đơn vị Bằng chứng (EvidenceUnit) & Trích xuất Tri thức
* **EvidenceUnit**: Mọi đoạn văn bản hoặc bảng biểu được chuẩn hóa thành `EvidenceUnit` mang mã băm nguồn `source_sha256`, số trang `pdf_page`, và tọa độ hình học `bbox`.
* **Trích xuất tất định (Deterministic)**:
  * Cấu trúc pháp lý (Điều, Khoản, Điểm): `legal_structure.py`, `article_tree.py`.
  * Bộ tiêu chí chấm điểm OCOP (Phiếu đánh giá, Tiêu chí): `criterion_sheets.py`.
  * Trình tự thủ tục hồ sơ (Mẫu biểu, Cơ quan thẩm quyền): `procedures.py`, `authorities.py`.
* **Trích xuất ngữ nghĩa (Semantic LLM Proposals)**:
  * Module `llm_proposals.py` gửi các đơn vị bằng chứng tới LLM (Ollama/OpenAI) để nhận diện các đặc trưng sản phẩm và thực thể bổ trợ, bắt buộc liên kết căn cứ với chuỗi ký tự gốc (`_align`).

### Tầng 3: Đồ thị Tri thức Một Đầu Ra (Single Graph Output)
* **Tệp đầu ra**: Hợp nhất toàn bộ tri thức vào `data/processed/ocop/graph/`:
  * `nodes.jsonl`: Danh sách nút thực thể kèm thuộc tính.
  * `edges.jsonl`: Danh sách cạnh quan hệ giữa các thực thể.
  * `manifest.json`: Chứa chữ ký phiên bản schema (`SCHEMA_REVISION`), số lượng, và mã băm SHA-256 của từng file.
* **Cờ kiểm chứng**: Mỗi đối tượng đồ thị mang nhãn `check` (`passed` hoặc `human_verified`) và `origin` (`deterministic`, `llm`, hoặc `human`). Nút/cạnh vi phạm bị loại bỏ vào `rejected.jsonl`.

### Tầng 4: Lập chỉ mục & Truy xuất (Indexing & Retrieval)
* **Chunking cấu trúc**: `structure_chunker.py` chia văn bản theo ranh giới điều khoản pháp lý và bảng biểu, kiểm soát ngân sách token (`DEFAULT_TARGET_CHUNK_TOKENS = 512`).
* **Chỉ mục kết hợp**:
  * **Sparse**: BM25 đa trường (từ khóa gốc + trường từ gập dấu `_fold_vietnamese`).
  * **Dense**: Vector nhúng 768 chiều tạo từ mô hình `google/embeddinggemma-300m`, lưu trữ tại Qdrant.
* **Xếp hạng lại (Reranking)**: Sử dụng `BAAI/bge-reranker-v2-m3` với ngân sách cặp token `DEFAULT_PAIR_TOKEN_BUDGET = 1024`. Tuyệt đối không bật `trust_remote_code`.

### Tầng 5: Điều phối, Lập kế hoạch & Cổng An toàn (Orchestration & Safety)
* **Phân tích câu hỏi (Router)** (`router.py`, `language.py`, `catalog.py`): trích slot (văn bản, điều, mẫu, phiếu, trang, tiêu chí, ngày, năm, địa danh, sản phẩm, chủ thể) từ từ vựng `configs/ocop_language.yaml` và danh mục thực thể sinh lúc dựng chỉ mục; chính sách riêng tư / nối tiếp / làm rõ / ngoài phạm vi rõ ràng (ADR-007). LLM chỉ gợi ý ý định thuộc enum.
* **Công cụ & Kế hoạch** (`planner.py`, `capabilities.py`, `tools.py`): năng lực chính và phụ; công cụ phụ không chặn câu trả lời; chỉ chạy công cụ trong `TOOL_REGISTRY`, tối đa 5 lượt. `tools_used` và `tools_skipped` phân biệt bước đã chạy và bước bị bỏ.
* **Truy xuất** (`search.py`, `settings.py`): BM25, vector (Qdrant) hợp nhất RRF có trọng số, rerank cross-encoder có ngân sách và cache; lỗi dense rơi về sparse kèm lý do (ADR-008).
* **Dựng context** (`context.py`, `graph_context.py`): chuỗi cha ngắn từ graph trong văn bản đánh chỉ mục; cửa sổ trích đoạn theo câu hỏi từ đoạn gốc; ngân sách trên toàn prompt; kiểm độ phủ thuật ngữ trên đúng khối SOURCE (ADR-006).
* **Câu trả lời theo claim** (`answer.py`, `verification.py`): LLM trả JSON claim kèm `[S#]`; mỗi claim qua cổng marker, cổng điểm/sao và cổng entailment; công bố phần qua cổng, nêu phần bị loại và phần nguồn chưa trả lời. Nguồn chưa duyệt không bao giờ được công bố là đã kiểm (ADR-002, ADR-005, ADR-009).
* **Phiên & riêng tư** (`sessions.py`, `privacy.py`): một `SessionStore` chung; định danh bị che trước khi lưu phiên/checkpoint; lỗi cấu hình trả 503 có schema.

### Tầng 6: Dịch vụ API & Giao diện (Web & UI)
* **API**: FastAPI phục vụ tại prefix `/api/ocop/*` (`backend/api/ocop_routes.py`), cung cấp các endpoint tra cứu tài liệu, xem PDF theo trang, kiểm tra sức khỏe và truy vấn trả lời.
* **Review UI**: Phục vụ hàng đợi duyệt người dùng và cập nhật nhật ký phê duyệt `ocop_review_decisions.jsonl`.
* **Frontend**: Ứng dụng React / Vite / TypeScript tại thư mục `frontend/`.

---

## 3. Bản đồ Vị trí Mã nguồn (Code Structure Map)

| Tầng chức năng | Thư mục mã nguồn chính | Các tệp nòng cốt |
| :--- | :--- | :--- |
| **Tiền xử lý & OCR PDF** | `ocr/ocop_ocr/`, `ocop_contracts/` | `pdf_pipeline.py`, `easy_viet_ocr.py`, `table_parser.py`, `artifact_cache.py`, `review.py` |
| **Trích xuất Tri thức** | `ai_core/knowledge/ocop/` | `extractor.py`, `criterion_sheets.py`, `legal_structure.py`, `llm_proposals.py` |
| **Đồ thị Tri thức** | `ai_core/graph/ocop/` | `builder.py`, `ontology.py`, `grounding.py`, `retriever.py`, `review.py` |
| **Chỉ mục & Chunking** | `ai_core/retrieval/ocop/` | `index_pipeline.py`, `structure_chunker.py`, `lookup.py` |
| **Tìm kiếm & Rerank** | `ai_core/retrieval/ocop/` | `search.py`, `fusion.py`, `settings.py`, `graph_context.py`, `models_config.py` |
| **Điều phối & An toàn** | `ai_core/orchestration/ocop/` | `workflow.py`, `router.py`, `language.py`, `catalog.py`, `planner.py`, `tools.py`, `context.py`, `answer.py`, `verification.py`, `sessions.py`, `privacy.py`, `llm.py` |
| **Điều khiển Hệ thống** | `ai_core/system/` | `pipeline.py`, `smoke.py`, `runtime.py`, `checkpoints.py` |
| **Dịch vụ API** | `backend/api/` | `ocop_main.py`, `ocop_routes.py`, `ocop_review_routes.py`, `ocop_debug.py` |
| **Dòng lệnh & Tiện ích** | `tools/` | `cli.py`, `debug_cli.py`, `evaluate_manual_pdf.py`, `evaluate_ocop.py`, `package_ocop.py` |
| **Giao diện Web** | `frontend/src/` | `ocop/Chat.tsx`, `ocop/Review.tsx`, `ocop/api.ts`, `pages/Dashboard.tsx` |
