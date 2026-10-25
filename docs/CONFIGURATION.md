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
* `OCOP_EXTRACT_LLM_REVISION`: (tùy chọn) chuỗi phiên bản/revision của mô hình trích xuất khi nhà cung cấp công bố; đổi giá trị này làm mất hiệu lực cache và tri thức đã trích.
* `OCOP_EXTRACT_LLM_WORKERS`: Số luồng trích xuất đồng thời. Mặc định: `4`.
* `OCOP_EXTRACT_LLM_GLEANINGS`: Số lượt đọc lại (gleaning iterations) để trích xuất tri thức sót. Mặc định: `1`.

### Cấu hình Đường dẫn Mô hình Cục bộ (Local Models & OCR)
* `OCOP_MODELS_DIR`: Thư mục lưu trữ các mô hình Hugging Face đã tải về máy (ví dụ: `D:/AgentAI/OCOP-RAG/models`). Khi được thiết lập, hệ thống tự động phát hiện và nạp mô hình offline không cần kết nối mạng.
* `OCOP_EASYOCR_MODEL_DIR`: Thư mục chứa trọng số mạng phát hiện ký tự CRAFT của EasyOCR (ví dụ: `craft_mlt_25k.pth`).
* `OCOP_VIETOCR_WEIGHTS`: Đường dẫn đến tệp trọng số VietOCR (ví dụ: `vgg_transformer.pth`).
* `OCOP_LAYOUT_MODEL_DIR`: Thư mục chứa mô hình nhận diện layout PaddleOCR (tùy chọn).

### Cấu hình Vận hành & Bảo mật
* `OCOP_ROOT`: Thư mục gốc của dự án. Mặc định tự động nhận diện từ vị trí mã nguồn.
* `OCOP_REVIEWERS_FILE`: Đường dẫn tệp JSON danh sách người duyệt (id, `token_sha256`, `can_decide`), đặt ngoài repo; thiếu thì API ghi quyết định từ chối (xem HUMAN_REVIEW.md).
* `OCOP_ENFORCE_RELEASE_GATE`: Cờ cưỡng chế kiểm tra cổng chất lượng trước khi phát hành (`1` là bật, `0` là tắt).
* `OCOP_LANGGRAPH_CHECKPOINT_ENABLED`: Bật tính năng lưu checkpoint phiên làm việc vào SQLite (`1` là bật, `0` là tắt).
* `OCOP_LANGGRAPH_CHECKPOINT_PATH`: Đường dẫn tệp SQLite lưu checkpoint (ví dụ: `checkpoints.sqlite`).

---

## 2. Các Tệp Cấu hình (configs/)

| Tệp cấu hình | Mục đích sử dụng |
| :--- | :--- |
| `configs/ocop_sources.json` | Danh mục 12 tài liệu văn bản quy phạm pháp luật và quyết định OCOP được phép nạp vào hệ thống. Quy định rõ mã `source_id`, đường dẫn `path`, số hiệu văn bản `document_number`, phạm vi địa lý `jurisdiction`, và loại văn bản `source_kind`. |
| `configs/ocop_sources.lock.json` | Khóa băm SHA-256 bất biến của từng tệp PDF và mã băm tổng hợp (`aggregate_sha256`). Mọi sự thay đổi về nội dung PDF sẽ bị từ chối khi nạp nếu không được phê duyệt lại bằng lệnh `python tools/cli.py debug lock-ocop`. |
| `configs/ocop_models.yaml` | Khai báo các mô hình chính thức, phiên bản thư viện tối thiểu, ngân sách token và chính sách an toàn. |
| `configs/ocop_authorities.json` | Danh mục chuẩn hóa các cơ quan có thẩm quyền ban hành và đánh giá phân hạng OCOP (UBND tỉnh, UBND huyện, Hội đồng OCOP...). |
| `configs/ocop_language.yaml` | Từ vựng tiếng Việt cho router/planner (mục 2.1). Có schema; test kiểm schema. |
| `configs/ocop_retrieval.yaml` | Tham số truy xuất, rerank, ngân sách context (mục 2.2). Có schema pydantic với giá trị mặc định. |
| `configs/ocop_privacy.yaml` | Mẫu che định danh trước khi lưu phiên/checkpoint (mục 2.3). |

### 2.1. `ocop_language.yaml`

Mọi danh sách từ khóa của router và planner nằm ở đây, khớp theo cụm từ nguyên vẹn và không phân biệt dấu (với câu có dấu thì đoạn đã gõ dấu phải bằng cụm cấu hình). Thêm cue = sửa tệp, không sửa mã.

| Khóa | Ý nghĩa |
| :--- | :--- |
| `stopwords`, `instruction_words` | Từ chức năng/mệnh lệnh: không tính là nội dung của câu hỏi |
| `document_types`, `document_number_markers` | Từ mở đầu tham chiếu văn bản ("Quyết định", "Luật") và chữ cái cuối số hiệu ("QĐ", "QH") để suy ra loại |
| `structure_nouns`, `star_noun`, `star_levels`, `certified_star_levels` | Danh từ cấu trúc (Điều, Mẫu, Phiếu, Trang, Tiêu chí) và thang hạng sao của khung đánh giá |
| `localities`, `locality_markers`, `locality_marker_blockers`, `nationwide_labels` | Tên đơn vị hành chính cấp tỉnh, tiền tố địa danh ("phường", "xã"), chỗ không được coi là địa danh ("cấp xã", "hợp tác xã"), nhãn "toàn quốc" |
| `entity_terminators`, `non_entity_phrases`, `product_markers` | Cắt tên sản phẩm khỏi cụm nghi vấn; từ không được là tên sản phẩm |
| `followup` | Từ mở đầu hội thoại ("còn", "thế") và đại từ ("nó", "cái đó") |
| `cues` | Cue theo ý định: thẩm quyền, chủ thể sản xuất, công nhận, thủ tục, tiêu chí, so sánh theo thời gian, an toàn thực phẩm, hồ sơ riêng tư, chấm điểm riêng tư, ngoài phạm vi rõ ràng, ... |
| `messages` | Thông điệp cho tuyến làm rõ và ngoài phạm vi |

Thực thể của corpus (số hiệu văn bản, sản phẩm, chủ thể, cơ quan, địa danh trong corpus, phiếu, mẫu) **không** nằm ở đây: chúng đến từ danh mục `data/processed/ocop/index/entity_catalog.json` sinh lúc dựng chỉ mục.

### 2.2. `ocop_retrieval.yaml`

| Khóa | Mặc định | Lý do |
| :--- | :---: | :--- |
| `context.prompt_token_budget` | 5200 | Cửa sổ trả lời 8192 token trừ phần dành cho đầu ra và biên an toàn của ước lượng token bảo thủ |
| `context.output_reserve_tokens` | 1024 | Bằng `max_tokens` của lượt sinh |
| `context.excerpt_max_chars` | 1500 | Đủ cho một khoản điều dài nhưng chừa chỗ cho 4–6 khối SOURCE |
| `context.table_excerpt_max_chars` | 5000 | Dòng bảng ngắn; giữ nguyên bảng khớp để không mất nhãn cột |
| `context.parent_chain_max_tokens` | 40 | Chuỗi cha chỉ để định vị; đo thấy mức này không làm chunk phình (trước đây +2500 ký tự) |
| `context.parent_label_max_chars` | 90 | Nhãn một khoản có thể dài hàng trăm ký tự |
| `context.min_term_coverage` | 0.25 | Dưới mức này gần như không có ý nào của câu hỏi trong SOURCE nên không sinh; thấp để không chặn câu hỏi dùng từ khác văn bản |
| `retrieval.top_k` | 8 | Số khối đưa vào ghép |
| `retrieval.candidate_pool_min` | 40 | Ứng viên của mỗi nhánh trước khi hợp nhất |
| `retrieval.rrf_k` | 60 | Giá trị chuẩn của RRF (Cormack và cộng sự) |
| `retrieval.rrf_weight_sparse/dense` | 1.0 / 1.0 | Chưa đo được lợi ích khi lệch trọng số trên bộ đo; để đối xứng |
| `retrieval.rerank_candidates` | 8 | Mỗi cặp 512 token mất ~1 giây trên 6 nhân CPU; 8 cặp giữ dưới 15 giây/câu |
| `retrieval.rerank_batch_size` | 4 | Giảm bộ nhớ đệm đỉnh trên máy 16 GB |
| `retrieval.rerank_threads` | 6 | Số nhân vật lý của máy chuẩn |
| `retrieval.rerank_cache_entries` | 512 | Cùng câu hỏi lặp lại không tốn thêm |
| `retrieval.query_max_chars` | 1500 | Chặn câu hỏi bất thường trước khi đếm token |

### 2.3. `ocop_privacy.yaml`

Danh sách `redactions` (`name`, `pattern`, `replacement`) áp dụng cho câu hỏi trước khi lưu vào phiên hoặc checkpoint: gán tenant/dossier/principal, mã dạng `ABC-001`, email, số điện thoại, token. Mẫu `private_handle` cũng được router dùng để nhận diện yêu cầu mở hồ sơ riêng.

### 2.4. Dấu vân tay trích xuất LLM và trạng thái semantic

Cache phản hồi và `knowledge/manifest.json` dùng cùng một dấu vân tay: nhà cung cấp, endpoint (đã bỏ thông tin đăng nhập và query), mô hình, `OCOP_EXTRACT_LLM_REVISION`, tham số lấy mẫu (nhiệt độ, `num_ctx` hoặc ngân sách suy luận), phiên bản mã/prompt, băm schema phản hồi, số lượt gleaning và giới hạn đơn vị. Số luồng và khóa API không nằm trong đó. `python tools/cli.py status` trả `semantic.state`: `disabled` (cố ý không chạy LLM, hợp lệ), `complete`, `partial` (chưa xử lý hết đơn vị đã chọn) hoặc `failed` (có lỗi); `partial` và `failed` làm corpus `not_ready`. `semantic_matches_config` cho biết cấu hình hiện tại còn trùng dấu vân tay đã lưu hay không.

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
  min_transformers_version: "4.57.0"

reranker:
  provider: sentence_transformers
  model_id: BAAI/bge-reranker-v2-m3
  revision: 953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
  pair_token_budget: 512

ocr:
  provider: easyocr_craft_vietocr_vgg_transformer_local_only
  candidates_require_human_review: true
```

* **Ngân sách Token (Token Budgets)**:
  * Chunk tiêu chuẩn: `DEFAULT_TARGET_CHUNK_TOKENS = 512`
  * Chiều dài tối đa mô hình nhúng: `DEFAULT_MODEL_MAX_TOKENS = 2048`
  * Ngân sách cặp văn bản khi Rerank: cấu hình `reranker.pair_token_budget` (mặc định mã nguồn 1024; cấu hình dự án 512 vì chi phí CPU tỉ lệ với độ dài cặp)

---

## 4. Dịch vụ Cơ sở Dữ liệu Ngoại vi (External Services)

* **Qdrant Vector DB** (Mặc định: `http://localhost:6333`):
  * Lưu trữ các điểm vector 768 chiều từ `EmbeddingGemma-300M` cho tìm kiếm dày đặc (dense retrieval).
  * Bộ sưu tập (collection): `ocop_dense_chunks`.
* **Neo4j** (Tùy chọn, mặc định: `bolt://localhost:7687`):
  * Dùng để lưu trữ và trực quan hóa đồ thị tri thức qua cờ `--neo4j` hoặc `--full`.
  * Tài khoản mặc định: `neo4j` / Mật khẩu: khai báo qua `NEO4J_PASSWORD`.
