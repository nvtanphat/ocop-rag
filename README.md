# OCOP GraphRAG

Hệ thống tra cứu tài liệu OCOP với trích dẫn truy ngược về PDF gốc, trang, vùng bằng chứng và mã SHA-256. Nội dung OCR chưa được duyệt được phân biệt với dữ liệu đã xác minh; điểm/sao chưa xác minh không dùng để kết luận xếp hạng.

PDF được khoá nguồn → dataset OCR độc lập → EvidenceUnit → đồ thị đã kiểm và chỉ mục → router giới hạn công cụ → kiểm chứng từng claim → API FastAPI và giao diện React. Backend phục vụ bản build frontend; mọi yêu cầu dữ liệu của giao diện đi qua `/api/ocop/*`. Không có dữ liệu tài liệu, sản phẩm hay tiêu chí viết cứng trong FE.

Cần Python 3.11+, Node.js 22.14+ và dependencies trong [DEVELOPMENT](docs/DEVELOPMENT.md). Khởi động giao diện và API bằng một lệnh PowerShell:

```powershell
.\run.ps1
```

Mở http://127.0.0.1:8000. Script build FE rồi chạy backend trong cùng terminal; Ctrl+C dừng dịch vụ. Với dataset OCR hoàn chỉnh trong `data/ocr-dataset`, lệnh sau dựng corpus rồi khởi động:

```powershell
.\run.ps1 -OcrDataset data/ocr-dataset
```

Dataset không đi kèm repo. Thiếu dataset không được coi là đã có corpus đầy đủ; xem trạng thái backend/corpus ở header. Quy trình chuẩn bị dữ liệu và Docker nằm trong [RUNBOOK](docs/RUNBOOK.md).

Kiểm thử từ gốc repo:

```powershell
python tools/cli.py --help
python -m pytest -q
ruff check .
Push-Location frontend
npm test
npm run build
Pop-Location
```

Tài liệu: [kiến trúc](docs/ARCHITECTURE.md), [cấu hình](docs/CONFIGURATION.md), [vận hành và review](docs/RUNBOOK.md), [phát triển](docs/DEVELOPMENT.md), [đánh giá](docs/EVALUATION.md), [thuật ngữ](GLOSSARY.md), [ADR](docs/adr/README.md), [OCR](ocr/README.md).
