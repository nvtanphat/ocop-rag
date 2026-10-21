# Hướng dẫn Đánh giá Chất lượng Hệ thống (Evaluation Guide)

Tài liệu hướng dẫn phương pháp đo lường, bộ dữ liệu benchmark, cách thực thi các công cụ đánh giá độc lập và nguyên tắc đọc hiểu kết quả trong OCOP GraphRAG.

---

## 1. Bộ Dữ liệu Benchmark Đối soát Thủ công

* **Tệp dữ liệu benchmark**: `data/evaluations/ocop/manual_pdf_benchmark.jsonl`.
* **Quy mô**: 126 câu hỏi đối soát trực tiếp từ 12 văn bản PDF gốc, trong đó:
  * 115 câu hỏi có căn cứ và trang đối chiếu cụ thể.
  * 11 câu hỏi thiếu căn cứ trong corpus hoặc ngoài phạm vi (dùng để kiểm thử khả năng từ chối trả lời).
* **Danh mục nguồn đối chiếu**: `data/evaluations/ocop/manual_pdf_sources.json` lưu trữ danh sách tài liệu, số trang và mã băm SHA-256 đối chiếu nguồn.
* **Nguyên tắc**: Dữ liệu do con người đọc và đối chiếu trực tiếp từ PDF; tuyệt đối không sinh nhãn vàng tự động từ mô hình hay pipeline.

---

## 2. Các Lệnh Thực thi Đánh giá

### Đánh giá Độ phủ Truy xuất trên PDF Benchmark (`evaluate_manual_pdf.py`)
Yêu cầu corpus đã được build trước (`python tools/cli.py run --build-only`).

```powershell
# Chạy đánh giá trên tập dev (phát triển)
python tools/evaluate_manual_pdf.py --split dev

# Chạy đánh giá trên tập test (kiểm thử)
python tools/evaluate_manual_pdf.py --split test

# Chạy toàn bộ 126 câu và xuất báo cáo kết quả ra tệp JSON
python tools/evaluate_manual_pdf.py --split all --out reports/evaluation/manual_pdf_report.json
```

### Đánh giá Tác tử & Mô phỏng Lỗi Tiêm nhiễm (`evaluate_ocop.py`)
```powershell
# Chạy đánh giá tác tử mặc định
python tools/evaluate_ocop.py

# Chạy đánh giá kèm kịch bản lỗi tiêm nhiễm (fault injection)
python tools/evaluate_ocop.py --with-faults
```

### Cưỡng chế Cổng Chất lượng Phát hành (Release Gate)
```powershell
# Kiểm tra điều kiện tiên quyết trước khi phát hành phiên bản
python tools/cli.py run --build-only --require-eval-gate
```
Khi cờ này được kích hoạt, hệ thống sẽ gọi `validate_latest` (`ai_core/evaluation/ocop/release.py`) để đối soát kết quả đánh giá mới nhất với mã băm dữ liệu gốc. Nếu không đạt yêu cầu, tiến trình sẽ báo lỗi và chặn phát hành.

---

## 3. Cách Đọc và Diễn giải Kết quả

### 1. Phân biệt Retrieval Coverage và Answer Correctness
* **Source-hit**: Tỷ lệ câu hỏi mà kết quả truy xuất tìm thấy đúng văn bản quy phạm gốc chứa câu trả lời.
* **Page-hit**: Tỷ lệ câu hỏi mà kết quả truy xuất tìm thấy đúng chính xác trang PDF chứa câu trả lời.
* **Lưu ý cốt lõi**: Đạt Source-hit hay Page-hit chỉ thể hiện tầng tìm kiếm (Retrieval) đưa được đoạn văn bản liên quan vào ngữ cảnh. Đây **không phải** là thước đo về độ chính xác của câu trả lời (`Answer Accuracy`) hay độ trung thực (`Faithfulness`). Để khẳng định câu trả lời đúng, hệ thống yêu cầu vượt qua cổng kiểm tra trích dẫn fail-closed (`verification.py`).

### 2. Số liệu Đo lường Baseline Đã Ghi nhận
Kết quả đo lường trên bộ benchmark 126 câu hỏi ở chế độ tìm kiếm sparse (BM25, không LLM):

| Tiêu chí đo lường | Giá trị đo được | Ghi chú |
| :--- | :---: | :--- |
| **Tổng số tài liệu / trang PDF** | 12 văn bản / 583 trang | Khóa băm SHA-256 |
| **Số câu hỏi thực thi** | 126 / 126 | Không có câu hỏi nào bị crash |
| **Source-hit (trên 115 câu có đáp án)** | 53,91% | Chế độ sparse BM25 thuần |
| **Page-hit (trên 115 câu có đáp án)** | 38,26% | Chế độ sparse BM25 thuần |
| **Answer Accuracy / Faithfulness** | Đo bằng Cổng Trích Dẫn | Yêu cầu 100% câu trả lời có viện dẫn hợp lệ |

* **Khuyến nghị nâng cấp**: Để nâng cao tỷ lệ hit trên văn bản ngữ nghĩa phức tạp, kích hoạt cờ tìm kiếm `--dense` (kết hợp Qdrant) và `--rerank` (kết hợp mô hình `bge-reranker-v2-m3`).
