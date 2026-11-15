# Đánh giá chất lượng

Gold evidence lấy từ ảnh PDF đã kiểm SHA, do người đọc nguồn ghi nhận; không sinh đáp án mong đợi từ đầu ra pipeline. Unit/contract test offline chứng minh bất biến, không phải thước đo chất lượng trên toàn corpus.

## Bộ đo

Các bộ dữ liệu đánh giá chuẩn (gold sets) được lưu tại `data/evaluations/ocop/`:

| Bộ | Vị trí | Quy mô | Cách dùng |
| --- | --- | --- | --- |
| Truy xuất tự nhiên | `data/evaluations/ocop/ocop_retrieval_gold_100_natural_final.json` | 100 câu | Đo Top-1, MRR, Recall@k theo trang (dataset_version `1.2.1-natural-query`) |
| Suy luận đa bước | `data/evaluations/ocop/ocop_graphrag_multihop_gold_25.json` | 25 câu (64 bước) | Đo độ phủ từng bước và tỷ lệ hoàn thành chuỗi multihop đầy đủ |
| Định tuyến router | `data/evaluations/ocop/ocop_router_gold_80.jsonl` | 80 câu | Đánh giá phân loại ý định (intent) và nhận diện phạm vi (scope) |
| Từ chối ngoài phạm vi | `data/evaluations/ocop/ocop_abstention_gold_20.json` | 20 câu | Kiểm tra khả năng từ chối trả lời an toàn khi câu hỏi ngoài phạm vi |
| Trích dẫn câu trả lời | `data/evaluations/ocop/ocop_answer_citation_gold_60.json` | 60 câu | Đối soát độ chính xác của trích dẫn `[S#]` và tính trung thực của claim |
| Trí nhớ phiên | `data/evaluations/ocop/ocop_session_memory_gold_50.json` | 50 lượt | Đo lường độ chính xác tìm trang khi câu hỏi nối tiếp có từ trỏ ngược |

Bộ giữ riêng (held-out) nằm ngoài repo, khoá bằng hash: chỉ xem số tổng, không điều chỉnh hệ thống theo từng ca của bộ này. Sáu bộ trên là bộ phát triển, chưa có file lock hash.

Không thay gold để khớp output. Nếu gold bị soạn sai, cần quy trình sửa/khóa riêng trước khi chạy lại.

## Chạy và chấm bằng `tools/evaluate_gold.py`

Một lệnh cho năm bộ `retrieval`, `multihop`, `session`, `abstention`, `citation` (bộ router dùng `tools/evaluate_router.py`). Mỗi dòng kết quả lưu (văn bản, trang) của từng trích dẫn theo thứ tự trong câu trả lời, nên vẫn chấm được sau khi dựng lại kho làm đổi mã đoạn. Lệnh `run` từ chối chạy khi tìm kiếm hybrid đang rơi về chỉ từ khoá.

```powershell
# nhóm nhỏ trước, cả bộ khi chốt
python tools/evaluate_gold.py run retrieval --sample 5 --seed 7 --out ../ocop-eval-runs/ret_try.jsonl
python tools/evaluate_gold.py run session --ids SM013,SM015 --real-for followup --out ../ocop-eval-runs/sm.jsonl
python tools/evaluate_gold.py run citation --ids R001,R091 --llm real --out ../ocop-eval-runs/cite.jsonl
python tools/evaluate_gold.py score retrieval ../ocop-eval-runs/ret.jsonl --compare ../ocop-eval-runs/ret_old.jsonl
```

`--llm stub` (mặc định) không sinh câu trả lời: số đo là bằng chứng vào prompt. `--real-for followup,aspects,scope` chỉ gửi các bước đó tới mô hình thật. Bộ `abstention` và `citation` cần `--llm real` mới có ý nghĩa. `--resume` chạy tiếp tệp đã có; với `session`, lệnh chạy nguyên các hội thoại chứa câu được chọn.

## Lưu ý kiểm tra hạ tầng trước khi đo (Docker Qdrant)

> [!IMPORTANT]
> Trước khi thực hiện bất kỳ phép đo lường nào (`hybrid` hoặc `rerank`), bắt buộc phải kiểm tra container Qdrant bằng lệnh:
> ```powershell
> docker ps --filter "name=ocop-qdrant"
> ```
> Trên máy phát triển có dung lượng RAM thấp hoặc ổ đĩa C gần đầy, Docker daemon có thể âm thầm tắt container `ocop-qdrant`.
> Khi Qdrant không sẵn sàng, hệ thống truy xuất sẽ tự động kích hoạt cơ chế suy thoái mềm (fallback), âm thầm chuyển sang tìm kiếm từ khóa thuần túy (sparse BM25) mà **không báo lỗi hay ngắt chương trình**. Điều này dẫn đến việc toàn bộ kết quả đo của chế độ `hybrid` bị tụt về điểm của BM25 mà người đo không nhận ra.
> 
> Nếu container bị tắt, bật lại bằng lệnh:
> ```powershell
> docker compose up -d qdrant
> ```
> Khi thực hiện đo lường đánh giá độc lập trên máy host, nên tắt container backend (`docker stop ocop-graphrag-backend-1`) để giải phóng toàn bộ tài nguyên CPU/RAM cho quá trình đánh giá.

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

`lane` (cũng ghi thành `execution_lane`) và `intent+lane` là nhãn của toàn kế hoạch, gồm công cụ phụ. `primary_lane` chỉ suy từ công cụ bắt buộc và được báo riêng thành `primary lane` và `intent+primary`. File `--out` ghi cả `required_tools`, `secondary_tools` và số công cụ được lên kế hoạch. Đây không phải số lần công cụ đã thực thi.

Gold có thể bổ sung `gold_required_tools`, `gold_allowed_tools`, `gold_forbidden_tools` bằng danh sách tên trong registry. Evaluator chấm số công cụ gold bắt buộc có trong required plan, và liệt kê công cụ bị cấm/ngoài tập cho phép trong toàn plan. Không có trường allowed nghĩa chưa ràng buộc tập cho phép, khác với `[]` là không cho phép công cụ nào. Chỉ tổng hợp các dòng có tool gold; nếu thiếu thì báo `tool correctness is not scored`, không tự tạo nhãn từ output router. Bộ 80 câu chưa có tool gold.

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

## Kết quả hiện tại

Chấm theo trang (mã nguồn, số trang PDF) trên corpus và graph đang phục vụ. Truy xuất dùng mô hình trả lời giả (`--llm stub`); router không gọi mô hình.

| Bộ đo | Chỉ số |
| --- | --- |
| Truy xuất, 100 câu (`ocop_retrieval_gold_100_natural_final.json`) | Top-1 75, MRR 0,848, Recall@3 0,94, Recall@5 0,99, Recall@10 1,0 |
| Router, 80 câu (`ocop_router_gold_80.jsonl`) | Ý định 65/80, luồng 52/80, phạm vi 77/80, slot 31/32 |

Citation, multihop, trí nhớ phiên và từ chối trả lời cần mô hình thật (`--llm real`); đo lại các bộ này sau mỗi thay đổi lớp trả lời trước khi ghi số vào bảng.
