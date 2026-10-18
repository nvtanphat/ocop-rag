# Hướng dẫn vận hành OCOP GraphRAG

## 1. Chuẩn bị

- Python 3.11+ và Tesseract OCR (`vie`, `eng`), RAM/ổ đĩa đủ để xử lý tài liệu scan.
- Node.js 22+ nếu cần giao diện React.
- Không commit `.env` hoặc dữ liệu hồ sơ riêng. Không sửa PDF nguồn và `configs/ocop_sources.lock.json` chỉ để vượt kiểm tra checksum.

## 2. Chạy toàn bộ luồng local

```powershell
python -m pip install -e '.[ocr,dev]'
python -m pytest -q tests/ocop
python tools/cli.py status
python tools/cli.py run --build-only --workers 4 --dpi 260
python tools/cli.py status
python tools/cli.py run --no-llm --workers 4 --dpi 260 --query 'Văn bản ở Huế đề cập đến sản phẩm hạt sen như thế nào?'
python tools/cli.py run --no-llm --workers 4 --dpi 260
```

Khi build hoàn tất, kiểm tra `state=ready` và `lineage_ok=true`. Chạy truy vấn thật và xem từng citation PDF; chỉ số sẵn sàng không chứng minh kết luận pháp lý là đúng.

Giữ `--dpi`, `--ocr-engine`, `--table-engine` nhất quán giữa các lần build và truy vấn. `--refresh` yêu cầu build lại các artifact; không xóa PDF nguồn.

## 3. API và giao diện

```powershell
cd frontend
npm ci
npm run dev
```

- `GET /api/ocop/health`
- `GET /api/ocop/sources`
- `POST /api/ocop/query` với JSON `{"query":"...", "use_llm":false}`
- `GET /api/ocop/sources/{source_id}/pdf`

## 4. Chạy benchmark sau build

```powershell
python tools/evaluate_manual_pdf.py --split all --out reports/evaluation/manual_pdf_sparse.json
```

Đây là tập **126 câu hỏi/đáp án được đối chiếu trực tiếp từ PDF**; chỉ chấm độ phủ trích dẫn trang và nguồn trong chế độ local sparse/no-LLM. Không coi page-hit là answer accuracy. Kết quả sinh ra tại `reports/` là **runtime output**, không nằm trong ZIP.

## 5. Xử lý lỗi và giới hạn

| Tình huống | Kiểm tra |
|---|---|
| `not_ready` | Rebuild index; so sánh checksum 12 PDF và manifest |
| OCR lỗi hoặc dữ liệu bảng trống | Tesseract `vie+eng`, quarantine, profile và bảng cần người duyệt |
| Truy vấn tự rebuild | Giữ DPI/OCR/table config khớp bản index đã build |
| Kết quả thiếu chứng cứ | Kiểm tra source scope, năm pháp lý, các trạng thái `needs_review` |
| Dense/Qdrant không có | Đây là tùy chọn; đừng gọi kết quả local sparse là hybrid |
| Frontend thiếu package | Cài Node/npm và chạy `npm ci` khi có mạng |

## 6. Trạng thái kiểm chứng

Một lần kiểm tra local đã xử lý 12 PDF / 583 trang, gồm 315 trang OCR; tạo 2.191 EvidenceUnits và dựng BM25/graph JSONL. Benchmark trên 115 câu có đáp án cho source-hit **53,91%** và page-hit **38,26%**. Đây là số liệu baseline ghi nhận, không phải kết quả mới từ bản ZIP sạch và không phải Answer Accuracy.

Phần bảng điểm OCR vẫn cần xác minh; chưa kiểm chứng live LLM/Ollama, Dense/Qdrant, Neo4j, MongoDB hoặc LangGraph trong lần chạy đó. Bản ZIP không chứa index build sẵn hoặc output đã tạo.
