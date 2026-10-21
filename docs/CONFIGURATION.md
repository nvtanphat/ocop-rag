# Cấu hình Hệ thống OCOP GraphRAG (Configuration Guide)

Tài liệu hướng dẫn toàn diện về các biến môi trường, tệp cấu hình tĩnh, định danh mô hình được ghim (pinned models) và dịch vụ lưu trữ ngoại vi.

---

## 1. Biến Môi trường (.env)

Hệ thống hỗ trợ nạp cấu hình tự động từ tệp `.env` tại thư mục gốc (xem `.env.example`). Nếu biến môi trường của hệ điều hành đã được thiết lập từ trước, giá trị đó sẽ luôn được ưu tiên (`os.environ.setdefault`).

### Cấu hình Mô hình Ngôn ngữ Sinh Câu hỏi & Trả lời (Answer LLM)
* `OCOP_ANSWER_LLM_PROVIDER`: Nhà cung cấp dịch vụ LLM cho việc trả lời câu hỏi. Mặc định: `ollama`. Giá trị hợp lệ: `ollama`, `openai`.
* `OCOP_LLM_MODEL`: Tên mô hình khi sử dụng Ollama cục bộ. Mặc định: `qwen3.5:2b`.
* `OCOP_OLLAMA_URL`: Địa chỉ máy chủ Ollama cục bộ. Mặc định: `http://127.0.0.1:11434`.
* `OCOP_ANSWER_LLM_MODEL`: Tên mô hình khi sử dụng OpenAI-compatible API (ví dụ: `gpt-6-sol`).
* `OCOP_ANSWER_OPENAI_BASE_URL`: URL máy chủ tương thích OpenAI cho tác vụ trả lời. Nếu để trống, sẽ dùng giá trị của `OCOP_EXTRACT_OPENAI_BASE_URL`.
* `OCOP_ANSWER_OPENAI_API_KEY`: Khóa API cho tác vụ trả lời. Nếu để trống, sẽ dùng giá trị của `OCOP_EXTRACT_OPENAI_API_KEY`.

### Cấu hình Mô hình Trích xuất Ngữ nghĩa (Extraction LLM)
* `OCOP_EXTRACT_LLM_PROVIDER`: Nhà cung cấp cho tác vụ trích xuất thực thể/quan hệ. Mặc định: `ollama`.
* `OCOP_EXTRACT_LLM_MODEL`: Tên mô hình trích xuất. Mặc định: `qwen3.5:2b` (Ollama) hoặc `gpt-5.6-sol` (OpenAI).
* `OCOP_EXTRACT_OPENAI_BASE_URL`: URL máy chủ OpenAI-compatible cho tác vụ trích xuất.
* `OCOP_EXTRACT_OPENAI_API_KEY`: Khóa API cho tác vụ trích xuất.
* `OCOP_EXTRACT_LLM_WORKERS`: Số luồng trích xuất đồng thời. Mặc định: `4`.
* `OCOP_EXTRACT_LLM_GLEANINGS`: Số lượt đọc lại (gleaning iterations) để trích xuất tri thức sót. Mặc định: `1`.

### Cấu hình Đường dẫn Mô hình Cục bộ (Local Models & OCR)
* `OCOP_MODELS_DIR`: Thư mục lưu trữ các mô hình Hugging Face đã tải về máy (ví dụ: `D:/AgentAI/OCOP-RAG/models`). Khi được thiết lập, hệ thống tự động phát hiện và nạp mô hình offline không cần kết nối mạng.
* `OCOP_EASYOCR_MODEL_DIR`: Thư mục chứa trọng số mạng phát hiện ký tự CRAFT của EasyOCR (ví dụ: `craft_mlt_25k.pth`).
* `OCOP_VIETOCR_WEIGHTS`: Đường dẫn đến tệp trọng số VietOCR (ví dụ: `vgg_transformer.pth`).
* `OCOP_LAYOUT_MODEL_DIR`: Thư mục chứa mô hình nhận diện layout PaddleOCR (tùy chọn).

### Cấu hình Vận hành & Bảo mật
* `OCOP_ROOT`: Thư mục gốc của dự án. Mặc định tự động nhận diện từ vị trí mã nguồn.
* `OCOP_REVIEW_TOKEN`: Mã bảo mật Bearer token dùng để xác thực quyền ghi quyết định thẩm định qua API `/api/ocop/review/decisions`.
* `OCOP_ENFORCE_RELEASE_GATE`: Cờ cưỡng chế kiểm tra cổng chất lượng trước khi phát hành (`1` là bật, `0` là tắt).
* `OCOP_LANGGRAPH_CHECKPOINT_ENABLED`: Bật tính năng lưu checkpoint phiên làm việc vào SQLite (`1` là bật, `0` là tắt).
* `OCOP_LANGGRAPH_CHECKPOINT_PATH`: Đường dẫn tệp SQLite lưu checkpoint (ví dụ: `checkpoints.sqlite`).

---

## 2. Các Tệp Cấu hình (configs/)

| Tệp cấu hình | Mục đích sử dụng |
| :--- | :--- |
| `configs/ocop_sources.json` | Danh mục 12 tài liệu văn bản quy phạm pháp luật và quyết định OCOP được phép nạp vào hệ thống. Quy định rõ mã `source_id`, đường dẫn `path`, số hiệu văn bản `document_number`, phạm vi địa lý `jurisdiction`, và loại văn bản `source_kind`. |
| `configs/ocop_sources.lock.json` | Khóa băm SHA-256 bất biến của từng tệp PDF và mã băm tổng hợp (`aggregate_sha256`). Mọi sự thay đổi về nội dung PDF sẽ bị từ chối khi nạp nếu không được phê duyệt lại bằng lệnh `python tools/cli.py debug lock-ocop`. |
| `configs/ocop_models.yaml` | Khai báo các mô hình chính thức, ngân sách token và chính sách an toàn. |
| `configs/ocop_authorities.json` | Danh mục chuẩn hóa các cơ quan có thẩm quyền ban hành và đánh giá phân hạng OCOP (UBND tỉnh, UBND huyện, Hội đồng OCOP...). |

---

## 3. Danh mục Mô hình & Revision Được Ghim (Pinned Models)

Hệ thống tuân thủ nguyên tắc bảo mật: **không tự động tải mã từ xa (`trust_remote_code=False`)** và luôn ghim cố định mã revision của mô hình:

```yaml
# configs/ocop_models.yaml
embedding:
  provider: sentence_transformers
  model_id: google/embeddinggemma-300m
  revision: 57c266a740f537b4dc058e1b0cda161fd15afa75
  dimension: 768
  model_max_tokens: 2048

reranker:
  provider: sentence_transformers
  model_id: BAAI/bge-reranker-v2-m3
  revision: 953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
  pair_token_budget: 1024

ocr:
  provider: easyocr_craft_vietocr_vgg_transformer_local_only
  candidates_require_human_review: true
```

* **Ngân sách Token (Token Budgets)**:
  * Chunk tiêu chuẩn: `DEFAULT_TARGET_CHUNK_TOKENS = 512`
  * Chiều dài tối đa mô hình nhúng: `DEFAULT_MODEL_MAX_TOKENS = 2048`
  * Ngân sách cặp văn bản khi Rerank: `DEFAULT_PAIR_TOKEN_BUDGET = 1024`

---

## 4. Dịch vụ Cơ sở Dữ liệu Ngoại vi (External Services)

* **Qdrant Vector DB** (Mặc định: `http://localhost:6333`):
  * Lưu trữ các điểm vector 768 chiều từ `EmbeddingGemma-300M` cho tìm kiếm dày đặc (dense retrieval).
  * Bộ sưu tập (collection): `ocop_dense_chunks`.
* **MongoDB** (Tùy chọn, mặc định: `mongodb://127.0.0.1:27017`):
  * Dùng để vật chất hóa các bản ghi cấu trúc và bảng biểu qua cờ `--mongo` hoặc `--full`.
  * Database: `ocop_rag`.
* **Neo4j** (Tùy chọn, mặc định: `bolt://localhost:7687`):
  * Dùng để lưu trữ và trực quan hóa đồ thị tri thức qua cờ `--neo4j` hoặc `--full`.
  * Tài khoản mặc định: `neo4j` / Mật khẩu: khai báo qua `NEO4J_PASSWORD`.
