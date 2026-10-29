# Cấu hình

`configs/ocop_sources.json` và `ocop_sources.lock.json` là danh mục và khoá nguồn. Không sửa PDF hay tái khoá để che việc bytes đã thay đổi.

| Cấu hình | Nguồn đọc |
| --- | --- |
| Từ vựng, ý định, địa danh, thang sao | `configs/ocop_language.yaml` |
| Ngân sách truy xuất, context, rerank và công cụ; ngưỡng nhận/loại câu trả lời (`min_term_coverage`, `grounding_min_term_coverage`, `min_quote_chars`, `max_quote_parts`, `part_min_coverage`, `source_agreement_share`) | `configs/ocop_retrieval.yaml` |
| Mô hình, revision và giới hạn tokenizer | `configs/ocop_models.yaml` |
| Che định danh trước khi lưu phiên/checkpoint | `configs/ocop_privacy.yaml` |
| Tên cơ quan | `configs/ocop_authorities.json` |

## Đường dẫn và dịch vụ

- `OCOP_ROOT`: gốc corpus cho API, đọc khi import ứng dụng. Launcher dùng repo hiện tại; không trỏ tới thư mục chứa corpus khác với frontend đang kiểm chứng.
- `OCOP_OCR_DATASET`: đường dẫn dataset OCR; mặc định `data/ocr-dataset`. `--ocr-dataset` của CLI hoặc `-OcrDataset` của `run.ps1` được ưu tiên. Docker gắn dataset read-only tại `/app/ocr-dataset`.
- `OCOP_RETRIEVAL_PROFILE`: `sparse` (mặc định) chỉ phục vụ BM25, từ chối yêu cầu dense/hybrid bằng HTTP 422. `hybrid` cần `sentence-transformers`, `qdrant-client`, chỉ mục dense và Qdrant truy cập được; thiếu điều kiện thì `/health` trả `not_ready` cùng `retrieval_profile.missing`, `/query` trả 503. Docker nhận giá trị qua build arg `OCOP_PROFILE`, `hybrid` cài thêm extra `retrieval`.
- `OCOP_LOG_LEVEL`: mức log của `ocop.*` (`INFO` mặc định); xem mục Quan sát trong [RUNBOOK](RUNBOOK.md).
- `OCOP_LLM_ROUTER`: `1` cho phép mô hình đề xuất intent với câu hỏi không có tín hiệu tất định nào, tốn thêm một lượt gọi mô hình (khoảng 10 giây); mặc định tắt, router tất định quyết định. Slot và công cụ vẫn chỉ nhận giá trị trong danh sách đã đăng ký.
- `OCOP_RERANK`: `1` bật reranker cho yêu cầu hybrid/dense (chỉ hợp lệ với `OCOP_RETRIEVAL_PROFILE=hybrid`); mặc định tắt. Tham số `rerank_candidates`, `rerank_first_stage_weight` nằm trong `configs/ocop_retrieval.yaml`. Mỗi cặp rerank tốn khoảng 1 giây CPU, câu hỏi có rerank thường mất 15–80 giây.
- `OCOP_SESSION_STORE`: `memory` (mặc định) hoặc `sqlite`; `OCOP_SESSION_DB` chọn tệp SQLite, mặc định `data/processed/ocop/sessions.sqlite3`.
- `OCOP_MODELS_DIR`: kho mô hình cục bộ cho embedding/reranker. Các model phải được chuẩn bị trước; không bật `trust_remote_code`.
- `OCOP_EASYOCR_MODEL_DIR`, `OCOP_VIETOCR_WEIGHTS`: trọng số OCR dùng trong dự án OCR riêng.
- `OCOP_LAYOUT_MODEL_DIR`: thư mục trọng số layout cục bộ cho thành phần OCR; chỉ dùng khi bật thành phần này.
- `OCOP_OCR_PEAK_LOCK`: tệp khóa tải/tính OCR giữa các tiến trình; mặc định `ocop-ocr-peak.lock` trong thư mục tạm hệ điều hành.
- `NEO4J_PASSWORD`: bí mật khi bật dịch vụ graph ngoài; không commit giá trị thực. `NEO4J_HEAP` (mặc định `512m`) và `NEO4J_PAGECACHE` (`256m`) giới hạn bộ nhớ container Neo4j trong `docker-compose.yml`; xuất bản graph cần khoảng 1 GB heap (`NEO4J_HEAP=1g`). Neo4j chỉ là nơi xuất bản graph, đường truy vấn đọc graph cục bộ.
- `OCOP_ENFORCE_RELEASE_GATE=1`: CLI từ chối phục vụ khi evaluation gate không đạt.
- `OCOP_LANGGRAPH_CHECKPOINT_ENABLED=1` và `OCOP_LANGGRAPH_CHECKPOINT_PATH`: bật SQLite checkpoint cho luồng có AuthContext tin cậy và session hợp lệ. API public không tự cấp quyền này.

Đặt `OCOP_RERANK=1` với profile `sparse` làm `/health` báo
`rerank_requires_hybrid_profile`; yêu cầu sparse không rerank. Tham số
`rerank_first_stage_weight` là trọng số RRF của thứ hạng tầng đầu khi hợp nhất
với reranker; giá trị 0 chỉ dùng thứ hạng cross-encoder.

Các tham số Qdrant/Neo4j và lựa chọn dense nằm trong trợ giúp CLI, không lấy từ request FE:

```powershell
python tools/cli.py run --help
```

## Mô hình truy vấn trên CPU

`retrieval.rerank_threads` trong `configs/ocop_retrieval.yaml` được đặt một lần trước khi nạp trọng số hoặc tính embedding/rerank. Khởi động lại tiến trình sau khi đổi số luồng. Embedding và reranker dùng chung khóa tải/tính toán để giới hạn bộ nhớ khi nhiều request đến đồng thời; request có thể chờ lượt tính mô hình.

`retrieval.tensor_reader_backend` nhận `auto`, `pread` hoặc `mmap`. `auto` chọn `pread` trên Windows và `mmap` trên hệ điều hành khác. Extra `retrieval`/`full` yêu cầu `safetensors>=0.8` để hỗ trợ bộ đọc này. Model, revision và chiều vector tiếp tục lấy từ cấu hình và manifest hiện hành; mọi lần nạp vẫn chỉ đọc trọng số cục bộ và giữ `trust_remote_code=false`.

Cache điểm rerank phân biệt ngân sách token của cặp câu hỏi/đoạn. Phản hồi vẫn ghi `rerank_input_truncated` khi đoạn bị cắt, kể cả khi dùng lại điểm đã cache. Kích thước nhóm ứng viên và trọng số RRF tiếp tục nằm trong cấu hình truy xuất.

`agent.lookup_max_rows` giới hạn số hàng bằng chứng của lookup cấu trúc (mặc định 15).
Lookup công nhận phân bổ ngân sách lần lượt theo bản ghi trước khi lấy thêm ô của
cùng bản ghi, để một bản ghi nhiều ô không che các sản phẩm khác.

`context.max_source_blocks` là giới hạn chung, kể cả các nguồn giữ chỗ cho facet,
quan hệ và ô liên quan. `context.max_table_siblings` (mặc định 3) giới hạn các ô
đi kèm cùng bản ghi trong ngân sách này. Nguồn không còn vừa ngân sách token sau
khi thu hẹp trích đoạn sẽ bị bỏ, kể cả khi chỉ còn một nguồn.

Tham chiếu: [khởi tạo luồng PyTorch](https://docs.pytorch.org/docs/stable/generated/torch.set_num_threads.html), [các bộ đọc Safetensors](https://huggingface.co/docs/safetensors/en/api/torch).

## LLM tùy chọn

`.env` được client LLM nạp khi cần; biến môi trường đã có được ưu tiên. FE không giữ key hay gọi nhà cung cấp LLM trực tiếp. Mặc định câu hỏi FE dùng `use_llm=false`; có thể bật sinh câu trả lời trên form.

| Biến | Ý nghĩa |
| --- | --- |
| `OCOP_ANSWER_LLM_PROVIDER` | `ollama` hoặc `openai`; mặc định Ollama |
| `OCOP_LLM_MODEL` | Tên model Ollama cho trả lời; mặc định `qwen3.5:2b` |
| `OCOP_OLLAMA_URL` | URL Ollama; mặc định `http://127.0.0.1:11434` |
| `OCOP_ANSWER_LLM_MODEL` | Model của endpoint OpenAI-compatible cho trả lời |
| `OCOP_ANSWER_OPENAI_BASE_URL`, `OCOP_ANSWER_OPENAI_API_KEY` | Endpoint và key cho trả lời; thiếu thì dùng cấu hình extraction tương ứng |
| `OCOP_EXTRACT_LLM_PROVIDER`, `OCOP_EXTRACT_LLM_MODEL` | Nhà cung cấp và model trích xuất ứng viên ngữ nghĩa |
| `OCOP_EXTRACT_OPENAI_BASE_URL`, `OCOP_EXTRACT_OPENAI_API_KEY` | Endpoint/key trích xuất |
| `OCOP_EXTRACT_LLM_REVISION` | Danh tính phiên bản model trong fingerprint |
| `OCOP_EXTRACT_LLM_WORKERS`, `OCOP_EXTRACT_LLM_GLEANINGS` | Mức song song và lượt đọc lại |

`run.ps1 -OcrDataset ...` dựng không dùng extraction LLM. Muốn dùng semantic extraction, gọi CLI `run` với cấu hình model đã sẵn sàng. Lỗi cấu hình LLM không được biến thành câu trả lời đã xác minh.

Hợp đồng endpoint và nguồn tham chiếu nằm trong [ARCHITECTURE](ARCHITECTURE.md#api-giao-diện);
cách chạy frontend cùng backend nằm trong [DEVELOPMENT](DEVELOPMENT.md#frontend).
