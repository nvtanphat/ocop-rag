# Cấu hình

`configs/ocop_sources.json` và `ocop_sources.lock.json` là danh mục và khoá nguồn. Không sửa PDF hay tái khoá để che việc bytes đã thay đổi.

| Cấu hình | Nguồn đọc |
| --- | --- |
| Từ vựng, ý định, địa danh, thang sao | `configs/ocop_language.yaml` |
| Ngân sách truy xuất, context, rerank và công cụ | `configs/ocop_retrieval.yaml` |
| Mô hình, revision và giới hạn tokenizer | `configs/ocop_models.yaml` |
| Che định danh trước khi lưu phiên/checkpoint | `configs/ocop_privacy.yaml` |
| Tên cơ quan | `configs/ocop_authorities.json` |

## Đường dẫn và dịch vụ

- `OCOP_ROOT`: gốc corpus cho API, đọc khi import ứng dụng. Launcher dùng repo hiện tại; không trỏ tới thư mục chứa corpus khác với frontend đang kiểm chứng.
- `OCOP_OCR_DATASET`: đường dẫn dataset OCR; mặc định `data/ocr-dataset`. `--ocr-dataset` của CLI hoặc `-OcrDataset` của `run.ps1` được ưu tiên. Docker gắn dataset read-only tại `/app/ocr-dataset`.
- `OCOP_RETRIEVAL_PROFILE`: `sparse` (mặc định) hoặc `hybrid`; xem [ARCHITECTURE](ARCHITECTURE.md). Docker nhận giá trị qua build arg `OCOP_PROFILE`, `hybrid` cài thêm extra `retrieval`.
- `OCOP_SESSION_STORE`: `memory` (mặc định) hoặc `sqlite`; `OCOP_SESSION_DB` chọn tệp SQLite, mặc định `data/processed/ocop/sessions.sqlite3`.
- `OCOP_MODELS_DIR`: kho mô hình cục bộ cho embedding/reranker. Các model phải được chuẩn bị trước; không bật `trust_remote_code`.
- `OCOP_EASYOCR_MODEL_DIR`, `OCOP_VIETOCR_WEIGHTS`: trọng số OCR dùng trong dự án OCR riêng.
- `NEO4J_PASSWORD`: bí mật khi bật dịch vụ graph ngoài; không commit giá trị thực.
- `OCOP_ENFORCE_RELEASE_GATE=1`: CLI từ chối phục vụ khi evaluation gate không đạt.
- `OCOP_LANGGRAPH_CHECKPOINT_ENABLED=1` và `OCOP_LANGGRAPH_CHECKPOINT_PATH`: bật SQLite checkpoint cho luồng có AuthContext tin cậy và session hợp lệ. API public không tự cấp quyền này.

Các tham số Qdrant/Neo4j và lựa chọn dense nằm trong trợ giúp CLI, không lấy từ request FE:

```powershell
python tools/cli.py run --help
```

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

## Reference verified

Mỗi dòng server-owned trong `data/processed/ocop/knowledge/verified_criteria.jsonl` hoặc `verified_products.jsonl` có `id`, `label`, `corpus_version`, `review_status`, `visibility` và `citations`. Citation gồm đầy đủ định danh nguồn/bằng chứng, trang, bbox, SHA. Không dùng tệp này để nhập dữ liệu từ người dùng hoặc LLM; không tạo bản ghi giả khi chưa có dữ liệu xác minh.

Không có cấu hình API base ở FE: client cố định `/api/ocop`. Vite proxy tới 8000; khi chạy bản build, frontend và API cùng origin.
