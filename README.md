# OCOP GraphRAG

Hệ thống tra cứu, suy luận và thẩm định văn bản quy phạm pháp luật, hồ sơ OCOP dựa trên kiến trúc GraphRAG tích hợp trích dẫn hình học chính xác từ PDF gốc.

Corpus gồm 12 văn bản PDF quy chuẩn được kiểm tra và khóa băm SHA-256 bất biến (`configs/ocop_sources.lock.json`).

---

## 1. Yêu cầu hệ thống

* **Python**: 3.11 trở lên (khuyến nghị Python 3.12).
* **Mô hình OCR cục bộ**: EasyOCR CRAFT detection và VietOCR VGG Transformer (không gọi API ngoài, nạp offline).
* **Mô hình nhúng & xếp hạng (tùy chọn)**: `google/embeddinggemma-300m` và `BAAI/bge-reranker-v2-m3`.
* **Mô hình ngôn ngữ (tùy chọn)**: Ollama cục bộ (`qwen3.5:2b`) hoặc API tương thích OpenAI.
* **Frontend**: Node.js 20+ (khuyến nghị Node.js 22).

---

## 2. Cài đặt và khởi chạy nhanh

### Cài đặt môi trường Python
```powershell
python -m pip install -e .
python -m pytest -q tests/ocop
```

### Kiểm tra trạng thái hệ thống
```powershell
python tools/cli.py status
```

### Xây dựng corpus (Build)
Trích xuất text, OCR các trang scan, xây dựng EvidenceUnits, tạo đồ thị tri thức duy nhất và chỉ mục tìm kiếm:
```powershell
python tools/cli.py run --build-only --dpi 300
```

### Hỏi đáp qua dòng lệnh (CLI)
```powershell
# Chế độ trích dẫn bằng chứng thuần túy (không cần LLM)
python tools/cli.py run --no-llm --query "Hồ sơ đề xuất đánh giá sản phẩm OCOP gồm những biểu mẫu nào?"

# Chế độ sinh câu trả lời với LLM cục bộ (Ollama)
python tools/cli.py run --query "Hồ sơ đề xuất đánh giá sản phẩm OCOP gồm những biểu mẫu nào?"
```

### Khởi chạy dịch vụ API
```powershell
python tools/cli.py run --no-llm --host 127.0.0.1 --port 8000
```
Kiểm tra API health: `http://127.0.0.1:8000/api/ocop/health`.

### Khởi chạy giao diện Frontend (React / Vite)
Tại cửa sổ dòng lệnh thứ hai:
```powershell
npm --prefix frontend run dev
```
Truy cập giao diện: `http://localhost:5173`.

---

## 3. Bản đồ Tài liệu Kỹ thuật

| Tài liệu | Mô tả |
| :--- | :--- |
| [Kiến trúc hệ thống](docs/ARCHITECTURE.md) | Luồng xử lý chi tiết từ PDF đến đồ thị và API; vị trí mã nguồn các tầng. |
| [Cấu hình & Biến môi trường](docs/CONFIGURATION.md) | Danh mục biến `.env`, các tệp cấu hình `configs/` và mô hình ghim. |
| [Vận hành & Runbook](docs/RUNBOOK.md) | Hướng dẫn build corpus, debug mẫu, chạy E2E và xử lý lỗi vận hành. |
| [Đánh giá chất lượng](docs/EVALUATION.md) | Bộ benchmark 126 câu hỏi đối soát PDF và cổng kiểm thử an toàn. |
| [Thẩm định người dùng](docs/HUMAN_REVIEW.md) | Quy trình phê duyệt bằng chứng, nhật ký review ledger và xác minh tri thức. |
| [Hướng dẫn phát triển](docs/DEVELOPMENT.md) | Quy chuẩn kiểm thử hermetic, quy ước commit và mở rộng tool/quan hệ. |
| [Thuật ngữ miền](GLOSSARY.md) | Định nghĩa các thực thể và trạng thái kiểm chứng miền OCOP. |
| [Quyết định kiến trúc (ADR)](docs/adr/README.md) | Các quyết định kỹ thuật nền tảng: đồ thị một đầu ra, cổng fail-closed, mô hình ghim. |
| [Dự án con OCR](ocr/README.md) | Pipeline OCR độc lập, hợp đồng dataset, duyệt Markdown và xuất nhập kiểm soát. |
