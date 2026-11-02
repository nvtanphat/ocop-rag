# Kết quả triển khai router sau nghiên cứu

Ngày: 2026-11-02. Thay đổi tiếp nối [hướng xử lý](router-solution-direction.md). Baseline code `92ec73c`; kết quả sau sửa được đo trên working tree. Gold 80 câu, câu mẫu semantic và ngưỡng 0,55/0,03 được giữ nguyên. Không dùng prediction từng câu sealed để chỉnh sửa.

## Những thay đổi đã áp dụng

- Intent bắt đầu từ cùng capability analysis với kế hoạch công cụ. Locator document+page có intent exact; quan hệ sửa đổi/thay thế có capability temporal/relation tương ứng.
- Tận dụng grammar tách câu đang có để nhận nhiều phần thực sự cùng đặt câu hỏi; không thêm một bộ decomposition khác.
- Tham chiếu đơn chỉ kế thừa một ứng viên duy nhất từ hội thoại, ưu tiên slot đã ghim. Không có ứng viên hoặc còn nhiều ứng viên thì hỏi rõ trước scope recovery. Tên địa phương đứng riêng không tự chứng minh câu thuộc OCOP.
- Luật yếu có thể hỏi model nếu embedding không đề xuất. Model chỉ trả primary/secondary intent hoặc yêu cầu clarification theo schema; server map sang capability/tool allowlist. Không nhận slot do adapter model tự đặt; không đổi document/version bằng output model.
- Override một nhu cầu không xóa capability độc lập của nhu cầu khác. Secondary intents từ model tối đa ba; planner và budget năm calls được giữ nguyên.
- Evaluator giữ `lane`/`intent+lane` cũ, bổ sung `primary_lane`, required/secondary tools và hỗ trợ gold tool sets riêng. Khi chưa có tool gold thì không báo tool correctness.

File chính: `ai_core/orchestration/ocop/router.py`, `memory.py`, `scope_model.py`, `configs/ocop_language.yaml`, `tools/evaluate_router.py`. Cập nhật hướng dẫn trong `docs/CONFIGURATION.md` và `docs/EVALUATION.md`.

## Đánh giá router

| Chế độ | Split | Intent trước → sau | Lane cũ trước → sau | Intent + lane cũ trước → sau |
|---|---|---:|---:|---:|
| Rules + embedding | Dev 40 | 31 → 38 | 26 → 29 | 21 → 28 |
| Rules + embedding | Sealed 40 | 27 → 27 | 23 → 23 | 18 → 18 |
| Rules + embedding + LLM | Dev 40 | 36 → 39 | 29 → 30 | 26 → 29 |
| Rules + embedding + LLM | Sealed 40 | 28 → 31 | 25 → 28 | 19 → 22 |

Gộp 80 câu, cùng định nghĩa metric cũ:

| Chế độ | Intent trước → sau | Intent + lane trước → sau |
|---|---:|---:|
| Rules + embedding | **72,5% → 81,25%** (58 → 65/80) | **48,75% → 57,5%** (39 → 46/80) |
| Rules + embedding + LLM | **80% → 87,5%** (64 → 70/80) | **56,25% → 63,75%** (45 → 51/80) |

Metric primary mới sau sửa:

- Rules + embedding: primary lane 59/80, intent+primary 54/80.
- Có LLM: primary lane 63/80, intent+primary 58/80.
- Slot: 31/32 ở cả hai chế độ; clarify 78/80 khi không có LLM, 80/80 khi có LLM.
- Scope: 77/80 khi không có LLM, 78/80 khi có LLM.

Không dùng metric primary mới để thay thế điểm cũ hay gọi là độ chính xác công cụ. Bộ 80 câu chưa có required/allowed/forbidden tool gold; chức năng chấm tool set chỉ được kiểm bằng fixture độc lập. Công cụ phụ vẫn được giữ, vì chưa có bằng chứng rằng tắt chúng cải thiện end-to-end.

Các lượt có model chạy một lần với API đang cấu hình, không pin response/revision và chưa đo variance/cost. Chênh lệch dev/sealed được công bố rõ: không có LLM, sealed intent chưa tăng. Kết quả này xác nhận sửa được các lỗi đã kiểm, chưa chứng minh generalization trên tập thứ ba hoặc chất lượng trả lời toàn bộ corpus.

## Kiểm tra tự động và corpus

- `python -X utf8 -m pytest -q`: **1264 passed, 2 skipped**, 3 cảnh báo deprecation từ dependencies; không có lỗi test.
- Ruff trên các file Python thay đổi: pass. `git diff --check`: pass.
- Nhóm hồi quy mới kiểm locator, scope địa phương, antecedent, model fallback, giữ nhu cầu phụ, enum/tool validation và tách metric lane/tool set. Đã chạy test đỏ trước khi sửa, sau đó chạy nhóm orchestration và toàn suite.
- Sửa một test distribution cũ vốn cấm toàn bộ `data/processed`, không còn phù hợp yêu cầu đưa runtime data lên GitHub. Test nay cho phép graph/index/knowledge/pages/system manifest, chỉ active graph snapshot; vẫn cấm cache, log, private data, local databases và OCR raw run state ngoài phạm vi.
- `python tools/cli.py status`: `ready`, `lineage_ok=true`, corpus `affccebc20166db51141`, graph `ce4db556b0af69a47a97`. Không sửa module tạo fingerprint extraction/graph/index, không cần rebuild hoặc re-embed.
- PDF, OCR, evidence units, provenance và file owner sửa trong `data/extraction` không bị thay đổi.

## Artifact và lệnh đo

[Bộ metric và artifact trong repo](../../data/evaluations/results/2026-11-02-router/README.md) có JSON tổng hợp đầy đủ, prediction dev trước/sau, smoke và năm bộ pipeline trước sửa. Bản gốc dev nằm ở `D:/AgentAI/ocop-eval-runs/router_impl_dev_final.jsonl`, `router_impl_dev_model.jsonl`. Sealed chỉ giữ số tổng hợp, không ghi prediction từng câu.

```powershell
python -X utf8 tools/evaluate_router.py --split dev --out D:/AgentAI/ocop-eval-runs/router_impl_dev_final.jsonl
python -X utf8 tools/evaluate_router.py --split dev --model --out D:/AgentAI/ocop-eval-runs/router_impl_dev_model.jsonl
python -X utf8 tools/evaluate_router.py --split sealed --sealed
python -X utf8 tools/evaluate_router.py --split sealed --sealed --model
```

## Smoke đầu cuối có LLM thật

Artifact: `D:/AgentAI/ocop-eval-runs/router_impl_citation_smoke.jsonl`.

| Ca citation gold | Trạng thái | Thời gian ghi trong kết quả |
|---|---|---:|
| R001 | `generated_claims_verified` | 121,2 giây |
| R029 | `partial_evidence` | 104,5 giây |
| R063 | `generated_claims_verified` | 53,5 giây |

Cả ba có `ok=true`, không exception. `partial_evidence` còn là giới hạn thực tế; không coi cả ba là đáp án đầy đủ. Không gộp smoke vào accuracy router hoặc coi đây là đánh giá lại toàn bộ 255 câu. Những trạng thái này không phải ước lượng answer accuracy và không đủ để quy toàn bộ khác biệt câu trả lời cho thay đổi router.

Lượt đầu chọn nhầm R061 không có trong citation gold; evaluator chỉ chạy hai ID hợp lệ. Đã bổ sung R063 bằng lượt `--resume` để có đủ ba ca. Lệnh để chạy lại đúng ba ID:

```powershell
python -X utf8 tools/evaluate_gold.py run citation --ids R001,R029,R063 --llm real --out D:/AgentAI/ocop-eval-runs/router_impl_citation_smoke_new.jsonl
```

Mã triển khai và bộ metric được lưu cùng bản cập nhật trên nhánh `dev`. Các báo cáo nghiên cứu trước được giữ làm lịch sử khảo sát, không sửa lại các kết luận ở thời điểm trước triển khai.
