# OCOP GraphRAG

Hệ thống tra cứu tài liệu OCOP kèm bằng chứng và số trang PDF. Corpus gồm **12 PDF nguồn** được khóa bằng SHA-256; nội dung gốc không chỉnh sửa.

## Cài đặt và khởi chạy

Yêu cầu Python 3.11+, Tesseract OCR (`vie` và `eng`); frontend cần Node.js 22+.

```powershell
python -m pip install -e '.[ocr,dev]'
python -m pytest -q tests/ocop
python tools/cli.py status
python tools/cli.py run --build-only --workers 4 --dpi 260
python tools/cli.py run --no-llm --workers 4 --dpi 260 --query 'Văn bản ở Huế đề cập đến hạt sen như thế nào?'
python tools/cli.py run --no-llm --workers 4 --dpi 260
```

Ở terminal khác, chạy frontend:

```powershell
cd frontend
npm ci
npm run dev
```

API: `http://127.0.0.1:8000/api/ocop/health`. Frontend: `http://localhost:5173`.

## Đánh giá độc lập

Tập đánh giá gồm **126 câu hỏi** đọc và đối chiếu trực tiếp từ PDF, có tệp nguồn, trang dẫn và checksum; không sinh đáp án từ kết quả pipeline.

```powershell
python tools/evaluate_manual_pdf.py --split dev
python tools/evaluate_manual_pdf.py --split test
python tools/evaluate_manual_pdf.py --split all
```

Lệnh đánh giá chỉ chạy khi corpus đã được build, kết quả mới được sinh vào `reports/` theo yêu cầu và **không được đóng gói**. Chỉ số retrieval không tương đương Answer Accuracy.

## Phạm vi và giới hạn

Luồng local mặc định: PDF → native text/OCR/table → EvidenceUnit → chunk → BM25 + graph JSONL → Router/Agent → trích dẫn PDF → API/React. Ollama, Qdrant/Dense, Neo4j, MongoDB và LangGraph thực tế là các tích hợp tùy chọn chưa được xác thực end-to-end trong môi trường kiểm tra.

Bản mã nguồn **không kèm output cũ, index, cache OCR, trạng thái session, bí mật cấu hình, báo cáo theo phiên bản hoặc script/test thử nhanh**. Cần build index lại từ PDF khi sử dụng. Không kết luận chất lượng SOTA chỉ từ pytest.

Xem [Hướng dẫn vận hành](docs/E2E_RUNBOOK.md), [Kiến trúc](docs/SYSTEM.md), [Đánh giá](docs/EVALUATION.md).
