# Đánh giá OCOP GraphRAG

## Dữ liệu gán nhãn thủ công

- `data/evaluations/ocop/manual_pdf_benchmark.jsonl`: 126 câu hỏi, trong đó 115 câu có đáp án tham chiếu và 11 câu thiếu căn cứ theo corpus.
- `data/evaluations/ocop/manual_pdf_sources.json`: danh sách tài liệu, trang và SHA-256 đối chiếu nguồn.
- Các nhãn là kết quả đọc/so trang PDF, **không** phải nhãn đã được chuyên gia OCOP xác nhận; không sinh gold labels từ pipeline hoặc dựa vào answer do LLM tự trả.

## Lệnh đánh giá

```powershell
python tools/cli.py run --build-only --dpi 300
python tools/evaluate_manual_pdf.py --split dev
python tools/evaluate_manual_pdf.py --split test
python tools/evaluate_manual_pdf.py --split all --out reports/evaluation/manual_pdf_sparse.json
```

Script xác minh checksum nguồn và chạy 126 câu qua Agent dùng BM25/no-LLM; xuất tool, intent, citation, page-hit, source-hit. Kết quả **chỉ là retrieval/citation coverage**, chưa đo Answer Accuracy, Faithfulness, robustness hoặc quality ranking theo nDCG.

## Số liệu baseline đã ghi nhận

| Chỉ số | Giá trị |
|---|---:|
| Tài liệu / trang PDF | 12 / 583 |
| Trang OCR | 315 |
| EvidenceUnits | 2.191 |
| Câu hỏi thực thi | 126/126 |
| Source-hit trên câu có đáp án | 53,91% |
| Page-hit trên câu có đáp án | 38,26% |
| Answer Accuracy / Faithfulness | Chưa đo |

Cần cải thiện OCR bảng điểm, đo Retrieval (Recall@K, nDCG có nhãn chunk), chạy real Dense/Rerank, chấm đúng sai từng claim bởi con người và kiểm tra hành vi từ chối khi thiếu căn cứ. Không trình bày baseline này như kết quả SOTA.
