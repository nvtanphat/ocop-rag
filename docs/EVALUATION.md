# Đánh giá chất lượng

Gold evidence lấy từ ảnh PDF đã kiểm SHA, do người đọc nguồn ghi nhận; không sinh đáp án mong đợi từ đầu ra pipeline. Unit/contract test offline chứng minh bất biến, không phải thước đo chất lượng trên toàn corpus.

## Bộ đo

| Bộ | Vị trí | Cách dùng |
| --- | --- | --- |
| Phát triển | `data/evaluations/ocop/dev_questions.json` và lock | Chỉnh router, retrieval, context |
| Benchmark đọc PDF thủ công | `data/evaluations/ocop/manual_pdf_benchmark.jsonl` | Độ phủ trên corpus đầy đủ |
| Bộ giữ riêng | Ngoài repo, khoá hash | Chỉ xem số tổng; không điều chỉnh theo từng ca |
| Hội thoại offline | `tests/fixtures/conversation_eval.json` | Kiểm chính sách phiên, làm rõ, đổi chủ đề |

Không thay gold để khớp output. Nếu gold bị soạn sai, cần quy trình sửa/khóa riêng trước khi chạy lại. Các bộ câu hỏi trong `data/evaluations` là dữ liệu đánh giá được giữ nguyên.

## Công cụ

```powershell
python tools/cli.py evaluate --help
python tools/evaluate_question_sets.py --help
python tools/evaluate_manual_pdf.py --help
python tools/evaluate_conversations.py --help
python tools/evaluate_reviewed_claims.py --help
```

`evaluate_question_sets` nhận `--root`, `--questions`, `--lock`, `--mode`, `--out`; `--sealed` chỉ in tổng. `--llm stub` chỉ thu prompt, không sinh câu trả lời; `--llm real` dùng cấu hình model thật. Chỉ dùng stub trong phép đo prompt, không dùng để tuyên bố chất lượng sinh.

`sparse` dùng BM25; `hybrid` thêm vector và RRF; `rerank` thêm cross-encoder. So sánh trên cùng corpus, graph/index version và câu hỏi đã khoá. Không gọi mạng/model trong pytest để thay thế một phép đo thực tế.

## Đọc kết quả

- `intent_ok`, `tool_ok`: đúng tuyến và công cụ, không dùng tool cấm.
- `page_in_prompt`, `content_ok`, `top1_page_ok`: đúng trang/nội dung thực sự vào SOURCE.
- `trap_safe`: không rò bí mật hoặc thực thi tool ngoài registry.
- `claims_published`, `claims_rejected`, `reject_reasons`: kết quả từng claim khi chạy LLM thật.
- `median_s`, `max_s`: thời gian; tách chi phí nạp model khỏi truy vấn ổn định khi so sánh.

Marker hoặc đúng trang chưa chứng minh entailment. Claim về điểm/sao cần kiểm số và nguồn verified; nội dung từ nguồn chưa duyệt phải giữ nhãn phù hợp. Không báo một ca bị chặn hoặc không có dữ liệu là PASS chất lượng trả lời.

Đánh giá claim verified chỉ nhận câu có EvidenceUnit đã duyệt; không có nguồn đủ điều kiện thì công cụ báo thiếu điều kiện. Quy trình duyệt nằm trong [RUNBOOK](RUNBOOK.md). Evaluation gate kiểm phiên bản corpus và kết quả; không dùng kết quả của commit/corpus cũ làm bằng chứng phát hành hiện tại.
