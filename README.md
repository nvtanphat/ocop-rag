# OCOP GraphRAG

Hệ thống tra cứu tài liệu OCOP kèm bằng chứng và số trang PDF. Corpus gồm 12 PDF nguồn được khóa bằng SHA-256; PDF gốc không bị chỉnh sửa.

## Cài đặt và khởi chạy

Yêu cầu Python 3.11+, model EasyOCR CRAFT và checkpoint VietOCR VGG Transformer được provision local; frontend cần Node.js 22+.

```powershell
python -m pip install -e '.[easy_vietocr,dev]'
python -m pytest -q tests/ocop
python tools/cli.py status
python tools/cli.py run --build-only --dpi 300
python tools/cli.py run --no-llm --dpi 300 --query 'Văn bản ở Huế đề cập đến hạt sen như thế nào?'
python tools/cli.py run --no-llm --dpi 300
```

Xem [hướng dẫn OCR](docs/PDF_EXTRACTION.md) để cấu hình model và đo chất lượng OCR.

Ở terminal khác, chạy frontend:

```powershell
cd frontend
npm ci
npm run dev
```

API: `http://127.0.0.1:8000/api/ocop/health`. Frontend: `http://localhost:5173`.

## Đánh giá độc lập

Tập đánh giá có 126 câu hỏi được đối chiếu trực tiếp từ PDF, kèm nguồn, trang dẫn và checksum.

```powershell
python tools/evaluate_manual_pdf.py --split dev
python tools/evaluate_manual_pdf.py --split test
python tools/evaluate_manual_pdf.py --split all
```

Lệnh đánh giá chỉ chạy khi corpus đã build. Kết quả được sinh vào `reports/` theo yêu cầu và không được đóng gói. Chỉ số retrieval không tương đương Answer Accuracy.

## Phạm vi và giới hạn

Luồng local mặc định: PDF native text hoặc EasyOCR CRAFT + VietOCR cho trang scan → EvidenceUnit → chunk → BM25 + graph JSONL → Router/Agent → trích dẫn PDF → API/React. Điểm OCR và dữ liệu bảng scan là ứng viên cần người rà soát; không dùng điểm OCR chưa xác minh để xếp hạng hoặc đánh giá hồ sơ. Ollama, Qdrant/Dense, Neo4j, MongoDB và LangGraph là các tích hợp tùy chọn.

Bản mã nguồn không kèm output OCR, index, cache, trạng thái session, bí mật cấu hình, báo cáo theo phiên bản hoặc dữ liệu hồ sơ riêng. Cần build index từ PDF nguồn khi sử dụng. Không kết luận chất lượng từ pytest.

Xem [hướng dẫn vận hành](docs/E2E_RUNBOOK.md), [kiến trúc](docs/SYSTEM.md), [đánh giá](docs/EVALUATION.md).
