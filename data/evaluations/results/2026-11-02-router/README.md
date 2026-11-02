# Metric và artifact đánh giá — 2026-11-02

Bản chụp kết quả đi cùng thay đổi router. [Metric JSON đầy đủ](metrics.json) chứa tử số, mẫu số, phần trăm, phân bố trạng thái và SHA-256 của từng artifact. [Báo cáo triển khai](../../../../docs/research/router-implementation-results.md) giải thích thay đổi và giới hạn.

## Router: giữ cùng định nghĩa metric trước/sau

Gold 80 câu không sửa. Dev 40 câu được phân tích; sealed 40 câu chỉ giữ số tổng hợp từ CLI. `lane` là nhãn toàn plan, gồm công cụ phụ.

| Chế độ | Split | Intent trước → sau | Lane trước → sau | Intent + lane trước → sau |
|---|---|---:|---:|---:|
| Rules + embedding | dev | 31/40 (77.5%) → 38/40 (95%) | 26/40 (65%) → 29/40 (72.5%) | 21/40 (52.5%) → 28/40 (70%) |
| Rules + embedding | sealed | 27/40 (67.5%) → 27/40 (67.5%) | 23/40 (57.5%) → 23/40 (57.5%) | 18/40 (45%) → 18/40 (45%) |
| Rules + embedding | combined | 58/80 (72.5%) → 65/80 (81.25%) | 49/80 (61.25%) → 52/80 (65%) | 39/80 (48.75%) → 46/80 (57.5%) |
| Rules + embedding + LLM | dev | 36/40 (90%) → 39/40 (97.5%) | 29/40 (72.5%) → 30/40 (75%) | 26/40 (65%) → 29/40 (72.5%) |
| Rules + embedding + LLM | sealed | 28/40 (70%) → 31/40 (77.5%) | 25/40 (62.5%) → 28/40 (70%) | 19/40 (47.5%) → 22/40 (55%) |
| Rules + embedding + LLM | combined | 64/80 (80%) → 70/80 (87.5%) | 54/80 (67.5%) → 58/80 (72.5%) | 45/80 (56.25%) → 51/80 (63.75%) |

## Chi tiết sau sửa

`primary_lane` chỉ suy từ required tools. Không thay metric cũ bằng metric này, và không diễn giải nó thành độ chính xác công cụ: bộ 80 câu chưa có tool gold.

| Chế độ | Split | Primary lane | Intent + primary | Hỏi rõ đúng | Scope đúng | Slot đúng |
|---|---|---:|---:|---:|---:|---:|
| Rules + embedding | dev | 33/40 (82.5%) | 33/40 (82.5%) | 40/40 (100%) | 40/40 (100%) | 16/17 (94.12%) |
| Rules + embedding | sealed | 26/40 (65%) | 21/40 (52.5%) | 38/40 (95%) | 37/40 (92.5%) | 15/15 (100%) |
| Rules + embedding | combined | 59/80 (73.75%) | 54/80 (67.5%) | 78/80 (97.5%) | 77/80 (96.25%) | 31/32 (96.88%) |
| Có LLM | dev | 34/40 (85%) | 34/40 (85%) | 40/40 (100%) | 40/40 (100%) | 16/17 (94.12%) |
| Có LLM | sealed | 29/40 (72.5%) | 24/40 (60%) | 40/40 (100%) | 38/40 (95%) | 15/15 (100%) |
| Có LLM | combined | 63/80 (78.75%) | 58/80 (72.5%) | 80/80 (100%) | 78/80 (97.5%) | 31/32 (96.88%) |

LLM scope calls: dev 7 → 5; sealed 2 → 9; tổng 9 → 14. Đây là số gọi hàm trong replay, có thể gồm history; không phải tỷ lệ người dùng phải hỏi model hoặc chi phí token. Model chạy một lần, không pin response/revision, chưa đo variance. Khi không có LLM, sealed intent giữ nguyên 27/40; không dùng 95% dev làm kết quả chung.

## Năm bộ pipeline: kết quả trước thay đổi router

Các file `pre-router-*` là lượt `full2` đã hoàn tất trước triển khai. Không chạy lại toàn bộ 255 câu sau sửa; commit chính xác lúc chạy gốc không được ghi lại. Trung bình thời gian và phân bố trạng thái đều có trong JSON.

| Bộ | Số câu / được chấm | Kết quả | TB giây/câu |
|---|---:|---|---:|
| [Retrieval](pre-router-retrieval.jsonl) | 100 / 100 | Any 100; all 100; top1 67; MRR 0,807; recall@3 0,95; @5 0,98; @10 1,0 | 40,1 |
| [Multihop](pre-router-multihop.jsonl) | 25 / 25 | 57/64 bước; 19/25 đủ mọi bước | 94,4 |
| [Session](pre-router-session.jsonl) | 50 / 49 | Any 45; all 42; top1 30; MRR 0,739; recall@3 0,837; @5 0,898; @10 0,918 | 34,9 |
| [Abstention](pre-router-abstention.jsonl) | 20 / 20 | Correct rejections 15/20; false-answer flags 5/20 | 32,1 |
| [Citation](pre-router-citation.jsonl) | 60 / 60 | Recall 0,864; precision 0,452; supported claims 89; required claims 102 | 63,8 |

Không có exception ở 255 câu. Session có một lượt không có gold source nên không chấm source recall. Abstention dùng không có cited pages làm proxy từ chối; 5 flags chưa được độc lập kết luận là hallucination. Citation precision/recall dựa trên trang gold; 89 claim supported không được đối chiếu một-một với 102 claim required nên không phải required-claim recall. Marker citation hợp lệ không chứng minh entailment.

## Smoke sau sửa

| Ca | Trạng thái | Giây |
|---|---|---:|
| R001 | `generated_claims_verified` | 121.2 |
| R029 | `partial_evidence` | 104.5 |
| R063 | `generated_claims_verified` | 53.5 |

[Ba dòng kết quả](citation-smoke-after.jsonl) có `ok=true`, không exception; R029 vẫn `partial_evidence`. Mẫu ba câu không thay thế evaluation 255 câu, không suy ra answer accuracy mới.

## Kiểm tra và artifact

- Pytest: 1264 passed, 2 skipped, 0 failed; 3 cảnh báo deprecation dependency. Đây là kiểm tra local, không phải GitHub Actions.
- Ruff và `git diff --check`: pass. Corpus status `ready`, lineage hợp lệ; không rebuild/re-embed, không thay PDF/gold/OCR.
- [Dev trước, không LLM](router-before-dev.jsonl); [dev trước, có LLM](router-before-dev-model.jsonl).
- [Dev sau, không LLM](router-after-dev.jsonl); [dev sau, có LLM](router-after-dev-model.jsonl).
- Không có prediction từng câu sealed trong bundle.
- `metrics.json.artifacts` ghi SHA-256 của bytes gốc được sao chép; `.gitattributes` giữ nguyên bytes khi checkout.

Để chấm lại số pipeline từ artifact, chạy `python tools/evaluate_gold.py score <set> <file>` từ gốc repo. Lệnh router và smoke để tái lập được ghi trong báo cáo triển khai; các lượt model mới có thể khác kết quả do API không được pin response.
