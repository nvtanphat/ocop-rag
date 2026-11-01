# Cấu hình

`configs/ocop_sources.json` và `ocop_sources.lock.json` là danh mục và khoá nguồn. Không sửa PDF hay tái khoá để che việc bytes đã thay đổi.

| Cấu hình | Nguồn đọc |
| --- | --- |
| Từ vựng, ý định, địa danh, thang sao | `configs/ocop_language.yaml` |
| Câu mẫu cho tầng embedding của router | `configs/ocop_router_examples.yaml` |
| Ngân sách truy xuất, context, rerank và công cụ; ngưỡng nhận/loại câu trả lời (`min_term_coverage`, `grounding_min_term_coverage`, `min_quote_chars`, `max_quote_parts`, `part_min_coverage`, `source_agreement_share`) | `configs/ocop_retrieval.yaml` |
| Mô hình, revision và giới hạn tokenizer | `configs/ocop_models.yaml` |
| Che định danh trước khi lưu phiên/checkpoint | `configs/ocop_privacy.yaml` |
| Tên cơ quan | `configs/ocop_authorities.json` |

## Đường dẫn và dịch vụ

- `OCOP_ROOT`: gốc corpus cho API, đọc khi import ứng dụng. Launcher dùng repo hiện tại; không trỏ tới thư mục chứa corpus khác với frontend đang kiểm chứng.
- `OCOP_OCR_DATASET`: đường dẫn dataset OCR; mặc định `data/ocr-dataset`. `--ocr-dataset` của CLI hoặc `-OcrDataset` của `run.ps1` được ưu tiên. Docker gắn dataset read-only tại `/app/ocr-dataset`.
- `OCOP_RETRIEVAL_PROFILE`: `sparse` (mặc định) chỉ phục vụ BM25, từ chối yêu cầu dense/hybrid bằng HTTP 422. `hybrid` cần `sentence-transformers`, `qdrant-client`, chỉ mục dense và Qdrant truy cập được; thiếu điều kiện thì `/health` trả `not_ready` cùng `retrieval_profile.missing`, `/query` trả 503. Docker nhận giá trị qua build arg `OCOP_PROFILE`, `hybrid` cài thêm extra `retrieval`.
- `OCOP_LOG_LEVEL`: mức log của `ocop.*` (`INFO` mặc định); xem mục Quan sát trong [RUNBOOK](RUNBOOK.md).
- `OCOP_LLM_ROUTER`: router có ba tầng, quy tắc luôn đi trước vì rẻ và nhanh. (1) Quy tắc tất định (từ vựng trong `ocop_language.yaml`) quyết định khi chắc: điểm từ `rule_confident_score` trở lên, hoặc có số hiệu, Điều, Phiếu, Mẫu, trang. (2) Khi quy tắc không có tín hiệu, hoặc điểm yếu, tầng embedding so câu hỏi với các câu mẫu trong `ocop_router_examples.yaml` bằng chính mô hình embedding của chỉ mục; nhãn gần nhất chỉ dùng khi đạt `semantic_min_score` và dẫn `semantic_min_margin` so với nhãn kế tiếp, và nhãn tổng quát `OCOP_OVERVIEW` không bao giờ ghi đè một quy tắc cụ thể. (3) Khi vẫn chưa rõ, mô hình chọn một nhãn trong danh sách đóng (`scope_model.py`, ép bằng schema enum), nhưng không chọn công cụ. Mảnh câu không có hội thoại ('1.6') không được hỏi mô hình mà để quy tắc hỏi lại. Nhãn không hợp lệ, mô hình lỗi hoặc không có chỉ mục dense thì giữ kết quả của tầng trước. `OCOP_LLM_ROUTER=1` mở thêm việc hỏi mô hình để chọn intent cho câu trong miền nhưng không khớp quy tắc nào; mặc định tắt. Đo router bằng `tools/evaluate_router.py` (xem [EVALUATION](EVALUATION.md)).
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

`retrieval.top_k` (mặc định `8`) là số đoạn trích tối đa một lần tìm kiếm trả về; các lần gọi `search` trong `tools.py` đọc trực tiếp từ khoá này thay vì đặt số cứng.

`retrieval.max_hits_per_document` (mặc định `3`, theo cơ chế `diversify_hits` của ViCAS-RAG): một lần tìm kiếm chỉ giữ tối đa 3 đoạn của cùng một văn bản nguồn ở nhóm ưu tiên trước khi lấy thêm các đoạn của văn bản khác; ngăn ngừa tình trạng văn bản ngắn hoặc hướng dẫn địa phương chiếm trọn 8 vị trí `top_k` và đẩy tài liệu quy chuẩn có câu trả lời ra ngoài.

`context.max_source_blocks` (đặt là `20`, nâng từ 10 lên 14 tại commit `7398e2d`, rồi nâng lên 20 tại commit `61965b4`) là giới hạn số khối nguồn tối đa trong một prompt trả lời sau khi ghép các đoạn tiếp nối và loại bỏ đoạn lặp lại. `context.max_table_siblings` (mặc định 3) giới hạn các ô đi kèm cùng bản ghi trong ngân sách này.

`context.prompt_token_budget` (đặt là `6400`, nâng tại commit `7398e2d`) là ngân sách token ước lượng tối đa cho toàn bộ prompt câu trả lời (system prompt + câu hỏi + các khối `SOURCE`). Phần dành cho các khối `SOURCE` là `prompt_token_budget − output_reserve_tokens (1024) − phần cố định của system prompt và câu hỏi`, nên `output_reserve_tokens` nằm bên trong 6400 chứ không cộng thêm. Cửa sổ mô hình trả lời là `llm.context_tokens` (8192) trong `ocop_models.yaml`, nên prompt tối đa khoảng 5400 token và còn khoảng 2800 token cho claim và trích dẫn. Nguồn không còn vừa ngân sách token sau khi thu hẹp trích đoạn sẽ bị bỏ, kể cả khi chỉ còn một nguồn.

`agent.lookup_max_rows` giới hạn số hàng bằng chứng của lookup cấu trúc (mặc định 15).
Lookup công nhận phân bổ ngân sách lần lượt theo bản ghi trước khi lấy thêm ô của
cùng bản ghi, để một bản ghi nhiều ô không che các sản phẩm khác.

Tham chiếu: [khởi tạo luồng PyTorch](https://docs.pytorch.org/docs/stable/generated/torch.set_num_threads.html), [các bộ đọc Safetensors](https://huggingface.co/docs/safetensors/en/api/torch).

## LLM tùy chọn

`.env` được client LLM nạp khi cần; biến môi trường đã có được ưu tiên. FE không giữ key hay gọi nhà cung cấp LLM trực tiếp. Mặc định câu hỏi FE dùng `use_llm=false`; có thể bật sinh câu trả lời trên form.

| Biến | Ý nghĩa |
| --- | --- |
| `OCOP_ANSWER_LLM_PROVIDER` | `openai` (API tương thích OpenAI; giá trị duy nhất được hỗ trợ) |
| `OCOP_ANSWER_LLM_MODEL` | Model cho trả lời; mặc định dùng `OCOP_EXTRACT_LLM_MODEL` (mặc định `gpt-6-sol`) |
| `OCOP_ANSWER_OPENAI_BASE_URL`, `OCOP_ANSWER_OPENAI_API_KEY` | Endpoint và key cho trả lời; thiếu thì dùng cấu hình extraction tương ứng |
| `OCOP_EXTRACT_LLM_PROVIDER`, `OCOP_EXTRACT_LLM_MODEL` | Nhà cung cấp và model trích xuất ứng viên ngữ nghĩa |
| `OCOP_EXTRACT_OPENAI_BASE_URL`, `OCOP_EXTRACT_OPENAI_API_KEY` | Endpoint/key trích xuất |
| `OCOP_EXTRACT_LLM_REVISION` | Danh tính phiên bản model trong fingerprint |
| `OCOP_EXTRACT_LLM_WORKERS`, `OCOP_EXTRACT_LLM_GLEANINGS` | Mức song song và lượt đọc lại |

`run.ps1 -OcrDataset ...` dựng không dùng extraction LLM. Muốn dùng semantic extraction, gọi CLI `run` với cấu hình model đã sẵn sàng. Lỗi cấu hình LLM không được biến thành câu trả lời đã xác minh.

Hợp đồng endpoint và nguồn tham chiếu nằm trong [ARCHITECTURE](ARCHITECTURE.md#api-giao-diện);
cách chạy frontend cùng backend nằm trong [DEVELOPMENT](DEVELOPMENT.md#frontend).
