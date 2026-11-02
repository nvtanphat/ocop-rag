# Đánh giá chất lượng

Gold evidence lấy từ ảnh PDF đã kiểm SHA, do người đọc nguồn ghi nhận; không sinh đáp án mong đợi từ đầu ra pipeline. Unit/contract test offline chứng minh bất biến, không phải thước đo chất lượng trên toàn corpus.

## Bộ đo

Các bộ dữ liệu đánh giá chuẩn (gold sets) được lưu tại `data/evaluations/ocop/` (commit `6cbab84`):

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

`lane` (cũng ghi thành `execution_lane`) và `intent+lane` giữ nghĩa cũ: nhãn của toàn kế hoạch, gồm công cụ phụ. `primary_lane` chỉ suy từ công cụ bắt buộc; báo riêng `primary lane` và `intent+primary`, không dùng để thay điểm cũ. File `--out` ghi cả `required_tools`, `secondary_tools` và số công cụ được lên kế hoạch. Đây không phải số lần công cụ đã thực thi.

Gold có thể bổ sung `gold_required_tools`, `gold_allowed_tools`, `gold_forbidden_tools` bằng danh sách tên trong registry. Evaluator chấm số công cụ gold bắt buộc có trong required plan, và liệt kê công cụ bị cấm/ngoài tập cho phép trong toàn plan. Không có trường allowed nghĩa chưa ràng buộc tập cho phép, khác với `[]` là không cho phép công cụ nào. Chỉ tổng hợp các dòng có tool gold; nếu thiếu thì báo `tool correctness is not scored`, không tự tạo nhãn từ output router. Bộ 80 câu hiện chưa có tool gold và được giữ nguyên trong thay đổi router này.

Bản chụp [metric và artifact ngày 2026-11-02](../data/evaluations/results/2026-11-02-router/README.md) gồm router trước/sau theo dev/sealed, JSON tổng hợp có tử số/mẫu số, prediction dev, smoke sau sửa và năm bộ pipeline trước sửa. [Báo cáo triển khai](research/router-implementation-results.md) ghi kiểm tra, thay đổi và giới hạn so sánh; không coi bộ pipeline cũ là phép đo lại sau sửa router.

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

## Kết quả đo lường đợt cải thiện (2026-11-01)

Mọi phép đo được thực hiện ngày 2026-11-01, chấm theo trang (mã nguồn, số trang PDF), với mô hình trả lời giả (`PromptCapture`) trừ khi ghi khác:

### 1. Truy xuất tự nhiên (dataset_version `1.2.1-natural-query`, 100 câu)
Bộ đo: `data/evaluations/ocop/ocop_retrieval_gold_100_natural_final.json`

| Commit | Thay đổi kỹ thuật | Top-1 | MRR | Recall@3 | Ghi chú |
| --- | --- | :---: | :---: | :---: | --- |
| `7398e2d` | Nâng context lên 14 khối nguồn, prompt budget 6400 token | - | - | - | Đo theo trang vào prompt: 97/95/61 → 98/95/62; trung bình đoạn/câu: 7,9 → 9,3 |
| `61965b4` | Nâng context lên 20 khối nguồn | - | - | - | Đo theo trang vào prompt: 98/95/62 → 99/98/61 |
| `7d29544`, `5b9558f` | Rerank cross-encoder 24 hàng đầu sau hợp nhất công cụ (RRF tool fusion) | 59 → 65 | 0,721 → 0,777 | 0,74 → 0,83 | Hòa điểm giữa vị trí 1 của các công cụ do cross-encoder phân định; thời gian tăng thêm ~8 s/câu trên CPU |

### 2. Suy luận đa bước (Multihop, 25 câu, 64 bước)
Bộ đo: `data/evaluations/ocop/ocop_graphrag_multihop_gold_25.json`

| Commit | Thay đổi kỹ thuật | Số bước đạt trang vàng | Số chuỗi hoàn thành đầy đủ | Ghi chú |
| --- | --- | :---: | :---: | --- |
| `7398e2d` | 14 khối nguồn, 6400 tokens | 46/64 → 51/64 | 13/25 → 15/25 | Mở rộng cửa sổ nhận đủ bằng chứng liên văn bản |
| `61965b4` | 20 khối nguồn | 51/64 → 52/64 | 15/25 → 16/25 | Bổ sung thêm các khối nguồn cho chuỗi dài |
| `207ef28` | Tìm kiếm cả aspects mô hình lẫn sub_queries theo luật | 50/64 → 52/64 | 13/25 → 16/25 | Đo với mô hình tách câu thật (các dòng khác dùng mô hình giả, không có `aspects`); khi câu con của mô hình thay phần tách theo luật thì còn 50 bước, dùng cả hai thì về lại 52 |
| `7d29544` | Cross-encoder toàn cục sau hợp nhất công cụ | 52/64 → 53/64 | 16/25 → 17/25 | Phân định đúng đoạn văn bản quy định dẫn đầu |
| `ec73930` | Giới hạn 3 đoạn mỗi văn bản (`max_hits_per_document`) | - | - | MH013 tăng thêm 2 bước đạt (QĐ26 trang 3 lọt vào top); 5 câu phức hợp ngẫu nhiên không đổi |

### 3. Trí nhớ phiên hội thoại (Session Memory, 50 lượt)
Bộ đo: `data/evaluations/ocop/ocop_session_memory_gold_50.json`

Bước viết lại câu nối tiếp gọi mô hình thật; các bước khác dùng mô hình giả.

| Commit | Thay đổi kỹ thuật | Trang vàng tìm đúng | Ghi chú |
| --- | --- | :---: | --- |
| `6630d15` | Mô hình viết lại câu trỏ ngược từ 3 câu gần nhất | 41/50 → 44/50 | Áp dụng kiểm thực từ vựng: không sáng tạo số và tên riêng |
| `5e200b2` | Giữ câu hỏi (`state_scope`) khi sản phẩm mới không có trong câu trước | 44/50 → 44/50 | SM013 và SM014 phục hồi đúng tên sản phẩm thay vì gán nhầm sang sản phẩm cũ |
| `909470f` | Nhận diện chữ viết tắt tên chủ thể ("HTX" và "Hợp tác xã") | 14/20 → 16/20 | Đo trên 4 hội thoại bị ảnh hưởng (SM013, SM015); 15 câu truy xuất gọi tên chủ thể không đổi |

### 4. Định tuyến Router (80 câu) và Dữ liệu trích xuất
- **Router (`ocop_router_gold_80.jsonl`, commit `1bc2129`)**: Giữ nguyên độ chính xác phân loại ý định 58/80 và phạm vi 76/80; 20 câu hỏi ngoài phạm vi (`ocop_abstention_gold_20.json`) từ chối đúng như cũ; ca SM033 được trả lời từ Nghị định 43 thay vì bị từ chối nhầm.
- **Dữ liệu trích xuất tiêu chí**:
  - Commit `3256090`: Nhận tiêu đề tiêu chí có đuôi chữ thường giúp giảm lỗi lệch tổng điểm cha/con từ 82 xuống 60.
  - Commit `c733115`: Khôi phục 32 tiền tố mục tiêu chí bị mất hoặc lỗi OCR trong QĐ148 sau khi đối soát PDF gốc, giảm lỗi lệch điểm từ 60 xuống 24.
  - Commit `ce226b9`: Nhận diện mốc chuyển tiếp quy phạm "sau N ngày/tháng/năm" tổng quát; số mốc thời gian không đổi.
