# Đánh giá chất lượng

Tài liệu mô tả các bộ đo, cách chạy và cách đọc kết quả. Thước đo gốc luôn là ảnh PDF đã kiểm mã SHA-256; mọi đáp án mong đợi do người đọc ảnh ghi, không sinh từ pipeline.

## 1. Ba loại bộ đo

| Bộ | Vai trò | Vị trí | Được dùng khi sửa? |
| :--- | :--- | :--- | :--- |
| Bộ phát triển (`dev_questions.json`) | Chỉnh route, công cụ, context, truy xuất | `data/evaluations/ocop/dev_questions.json` (+ `.lock.json`) | Có |
| Bộ giữ riêng (held-out) | Chứng minh không quá khớp | Ngoài repo; chỉ lưu mã băm | Không: chỉ xem số tổng |
| Benchmark thủ công 126 câu | Độ phủ truy xuất toàn corpus | `data/evaluations/ocop/manual_pdf_benchmark.jsonl` | Có (cần corpus đầy đủ) |

Bộ giữ riêng gồm câu hỏi soạn từ các trang **không** nằm trong mẫu dùng để phát triển, đáp án và trang được ghi trước khi chạy, tệp bị khóa bằng SHA-256. Quy tắc: không mở kết quả từng câu trong lúc sửa; mỗi vòng chỉ so số tổng. Nếu phải sửa một câu hỏi vì lỗi soạn thảo, sửa trước khi chạy, ghi lý do trong trường `correction` và khóa lại; không sửa đáp án để khớp kết quả hệ thống.

## 2. Định dạng câu hỏi

```json
{"id": 19, "query": "...", "source_id": "<registry source_id>", "pages": [3],
 "expected": "đáp án người viết", "evidence_phrases": ["cụm phải có trong prompt"],
 "expected_intents": ["exact_lookup"], "required_any_tools": ["lookup_legal_unit"],
 "forbid_tools": [], "forbid_intents": [], "turns": ["lượt 1", "lượt 2"], "trap": "injection"}
```

`required_any_tools` rỗng nghĩa là câu hỏi không cần công cụ (làm rõ, ngoài phạm vi). `conversation` hoặc `turns` mô tả hội thoại nhiều lượt; chỉ lượt cuối được chấm.

## 3. Chạy

```powershell
# Lõi: không LLM; ghi lại đúng prompt SOURCE sẽ gửi cho LLM
python tools/evaluate_question_sets.py --root <thư mục corpus> --questions data/evaluations/ocop/dev_questions.json `
    --lock data/evaluations/ocop/dev_questions.lock.json --mode hybrid --out reports/dev-hybrid.json

# Bộ giữ riêng: chỉ in tổng
python tools/evaluate_question_sets.py --root <corpus giữ riêng> --questions <holdout.json> --lock <lock.json> --mode hybrid --sealed
```

Chế độ: `sparse` (BM25), `hybrid` (BM25 + vector, RRF), `rerank` (hybrid + cross-encoder). `--llm real` dùng LLM cấu hình trong `.env`.

Các công cụ cũ vẫn dùng được cho phần còn lại: `tools/evaluate_manual_pdf.py` (benchmark 126 câu, cần corpus đầy đủ), `tools/evaluate_ocop.py` (tác tử và tiêm lỗi), `python tools/cli.py run --build-only --require-eval-gate` (cổng phát hành).

## 4. Chỉ số

| Chỉ số | Ý nghĩa |
| :--- | :--- |
| `intent_ok` | Ý định nằm trong tập mong đợi và không thuộc tập cấm |
| `tool_ok` | Có ít nhất một công cụ mong đợi (hoặc không công cụ nào khi không cần) và không có công cụ cấm |
| `page_in_prompt` | Trang đích nằm trong khối SOURCE gửi cho LLM (đo trên prompt thật, không phải trên đầu ra công cụ) |
| `content_ok` | Trang đích **và** mọi cụm `evidence_phrases` nằm trong prompt: đủ nội dung để trả lời |
| `top1_page_ok` | Khối SOURCE đầu tiên thuộc trang đích |
| `trap_safe` | Câu bẫy (tiêm lệnh, khóa API) không rò rỉ và không chạy công cụ ngoài registry |
| `median_s`, `max_s` | Thời gian mỗi câu; lượt đầu gồm cả nạp mô hình nên chỉ so sánh lượt sau |

Với `--llm real` công cụ bọc client thật bằng `RecordingClient` nên các chỉ số trên được tính trên đúng prompt đã gửi; thêm các chỉ số tầng trả lời (không có ở `stub`, vì client giả không sinh văn bản):

| Chỉ số | Ý nghĩa |
| :--- | :--- |
| `raw_excerpt` | Số câu rơi về trích đoạn thô (`citation_verification_failed`, `insufficient_context_for_generation`, `retrieval_only`, `model_unavailable_retrieval_only`) |
| `claims_published` / `claims_rejected` | Claim qua / không qua cổng từng claim; lý do từng câu nằm trong `reject_reasons` |

Kết quả `--llm real` dao động giữa các lần chạy (mô hình không tất định): so sánh bằng tổng trên cả bộ và đọc lại từng ca trước khi quy cho mã.

`page_in_prompt` chỉ chứng minh tầng truy xuất và dựng context đưa được trang đúng vào prompt. Nó **không** chứng minh câu trả lời đúng: điều đó do cổng claim và cổng điểm/sao quyết định (ADR-002, ADR-005).

## 5. Kiểm diễn giải trên nguồn đã duyệt

`python tools/evaluate_reviewed_claims.py --root <corpus> --questions <câu hỏi>` chỉ chạy các câu mà mọi trang đích có ít nhất một EvidenceUnit `human_verified` trong graph hiện tại, rồi báo mỗi câu: claim nào được công bố, claim nào bị loại và lý do, phần nguồn chưa trả lời. Công cụ không đánh dấu `verified` và không nới cổng; chưa có nguồn nào được duyệt thì nó dừng (mã thoát 2) và chỉ đường duyệt (`review queue --render`, xem HUMAN_REVIEW.md). Sau mỗi quyết định duyệt, graph và chỉ mục được cập nhật cùng nhau.

## 6. Lưu ý đọc kết quả

* Corpus mẫu và corpus giữ riêng đều chưa có bằng chứng `verified`; vì cổng claim yêu cầu nguồn đã duyệt nên số câu LLM được công bố là 0 cho tới khi người duyệt Markdown. Đây là thiết kế, không phải lỗi.
* Câu hỏi về chắc chắn một hạng sao dựa trên OCR được kỳ vọng bị chặn; trang đích không vào prompt là kết quả an toàn, không phải lỗi truy xuất.
* Sau mỗi thay đổi mã trong `ai_core/graph`, `ai_core/retrieval` hoặc mô-đun trích xuất, dựng lại graph và chỉ mục (`build_sample.py --reindex`): phiên bản kiểm tra graph gắn với mã nguồn.
