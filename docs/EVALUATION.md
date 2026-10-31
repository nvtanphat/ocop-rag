# Đánh giá chất lượng

Gold evidence lấy từ ảnh PDF đã kiểm SHA, do người đọc nguồn ghi nhận; không sinh đáp án mong đợi từ đầu ra pipeline. Unit/contract test offline chứng minh bất biến, không phải thước đo chất lượng trên toàn corpus.

## Bộ đo

| Bộ | Vị trí | Cách dùng |
| --- | --- | --- |
| Phát triển | `data/evaluations/ocop/dev_questions.json` và lock | Chỉnh router, retrieval, context |
| Benchmark đọc PDF thủ công | `data/evaluations/ocop/manual_pdf_benchmark.jsonl` | Độ phủ trên corpus đầy đủ |
| Bộ giữ riêng | Ngoài repo, khoá hash | Chỉ xem số tổng; không điều chỉnh theo từng ca |
| Hội thoại offline | `tests/fixtures/conversation_eval.json` | Kiểm chính sách phiên, làm rõ, đổi chủ đề |

Không thay gold để khớp output. Nếu gold bị soạn sai, cần quy trình sửa/khóa riêng trước khi chạy lại.

Repo hiện không chứa bộ dữ liệu đánh giá nào trong `data/evaluations/ocop/`; bộ cũ vẫn tra được trong lịch sử Git. Khi thêm bộ mới, đặt đúng tên và vị trí ở bảng trên (các công cụ đọc đường dẫn mặc định đó, hoặc nhận `--dataset`/`--questions`), kèm lock hash cho bộ phát triển. Hai test dữ liệu đánh giá tự bỏ qua khi không có file và tự chạy lại khi file xuất hiện. `tools/cli.py evaluate` và cổng phát hành `validate_latest` cần `retrieval_page_gold_seed.jsonl` nên chưa chạy được cho tới khi bộ đó có mặt.

## Công cụ

```powershell
python tools/cli.py evaluate --help
python tools/evaluate_question_sets.py --help
python tools/evaluate_manual_pdf.py --help
python tools/evaluate_conversations.py --help
python tools/evaluate_router.py --help
python tools/evaluate_reviewed_claims.py --help
```

`evaluate_question_sets` nhận `--root`, `--questions`, `--lock`, `--mode`, `--out`; `--sealed` chỉ in tổng. `--llm stub` chỉ thu prompt, không sinh câu trả lời; `--llm real` dùng cấu hình model thật. Chỉ dùng stub trong phép đo prompt, không dùng để tuyên bố chất lượng sinh.

`sparse` dùng BM25; `hybrid` thêm vector và RRF; `rerank` thêm cross-encoder. So sánh trên cùng corpus, graph/index version và câu hỏi đã khoá. Không gọi mạng/model trong pytest để thay thế một phép đo thực tế.

`evaluate_router` chấm router trên một bộ câu hỏi có nhãn (mặc định `data/evaluations/ocop/ocop_router_gold_80.jsonl`): đúng ý định, đúng luồng (lane), hỏi lại, phạm vi, slot; theo từng nhãn và từng thẻ, kèm ma trận nhầm lẫn. Mỗi câu chạy `route` rồi `plan` của agent như `ask`, các câu trước trong hội thoại dựng phiên bằng đúng `next_state` của API; không công cụ nào chạy và không gọi mô hình trừ khi có `--model` (tầng LLM của router, báo cả tỉ lệ câu phải hỏi mô hình). `--no-semantic` tắt tầng embedding. Hàng không có trường `split` được chia cố định theo id: số lẻ là `dev` (được xem từng câu sai để chỉnh), số chẵn là `sealed` (chỉ xem tổng bằng `--split sealed --sealed`, không chỉnh router theo từng câu). Gold gán theo nguồn nào trả lời được câu hỏi, không theo kết quả router.

## Cổng phát hành

`tools/evaluate_ocop.py --with-agent --with-faults --claims-questions <tệp>` gộp truy xuất, quỹ đạo công cụ, đánh giá claim và lỗi giả lập vào một báo cáo rồi chạy `release_gate`; `--strict` thoát mã 2 khi bị chặn. Chế độ production chặn khi thiếu nhãn chuyên gia, thiếu một trong `sparse`/`dense`/`hybrid`, thiếu quỹ đạo, claim grounding, hoặc lỗi giả lập. Các ngưỡng mặc định (`GATE_DEFAULTS` trong `harness.py`, ghi đè qua `thresholds`):

| Điều kiện | Ngưỡng |
| --- | --- |
| `tool_recall` của quỹ đạo | ≥ 0,9 |
| Số ca Agent lỗi (`errors`) | 0 |
| Tỉ lệ claim được công bố hoặc công bố một phần (`publish_rate`) | ≥ 0,5, trên ít nhất một câu hỏi đủ điều kiện |
| Gọi công cụ bị cấm | 0 |
| Hồi quy so với baseline | `recall_at_10`, `tool_recall`, `publish_rate` không giảm quá 0,03 |

Đánh giá claim chỉ chạy trên câu hỏi có EvidenceUnit lấy từ chữ OCR đã duyệt và cần LLM thật.

## Đọc kết quả

- `intent_ok`, `tool_ok`: đúng tuyến và công cụ, không dùng tool cấm.
- `page_in_prompt`, `content_ok`, `top1_page_ok`: đúng trang/nội dung thực sự vào SOURCE.
- `trap_safe`: không rò bí mật hoặc thực thi tool ngoài registry.
- `claims_published`, `claims_rejected`, `reject_reasons`: kết quả từng claim khi chạy LLM thật.
- `median_s`, `max_s`: thời gian; tách chi phí nạp model khỏi truy vấn ổn định khi so sánh.

Marker hoặc đúng trang chưa chứng minh entailment. Claim về điểm/sao cần kiểm số và nguồn verified; nội dung từ nguồn chưa duyệt phải giữ nhãn phù hợp. Không báo một ca bị chặn hoặc không có dữ liệu là PASS chất lượng trả lời.

Đánh giá claim verified chỉ nhận câu có EvidenceUnit từ chữ OCR đã duyệt; không có nguồn đủ điều kiện thì công cụ báo thiếu điều kiện. Cách sửa chữ OCR nằm trong [RUNBOOK](RUNBOOK.md). Evaluation gate kiểm phiên bản corpus và kết quả; không dùng kết quả của commit/corpus cũ làm bằng chứng phát hành hiện tại.
