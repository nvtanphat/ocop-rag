# Hướng dẫn vận hành OCOP GraphRAG

## 1. Chuẩn bị

- Python 3.11+, EasyOCR CRAFT và checkpoint VietOCR VGG Transformer đã được provision local.
- Node.js 22+ nếu cần giao diện React.
- Không commit `.env` hoặc dữ liệu hồ sơ riêng. Không sửa PDF nguồn và `configs/ocop_sources.lock.json` để vượt kiểm tra checksum.

Xem [hướng dẫn OCR](PDF_EXTRACTION.md) để cấu hình model.

## 2. Chạy toàn bộ luồng local

```powershell
python -m pip install -e '.[easy_vietocr,dev]'
python -m pytest -q tests/ocop
python tools/cli.py status
python tools/cli.py run --build-only --dpi 300
python tools/cli.py status
python tools/cli.py run --no-llm --dpi 300 --query 'Văn bản ở Huế đề cập đến sản phẩm hạt sen như thế nào?'
python tools/cli.py run --no-llm --dpi 300
```

Khi build hoàn tất, kiểm tra `state=ready` và `lineage_ok=true`. Chạy truy vấn thật và xem từng citation PDF; trạng thái sẵn sàng không chứng minh kết luận pháp lý là đúng.

Giữ `--dpi` nhất quán giữa các lần build và truy vấn. `--refresh` yêu cầu build lại artifacts; không xóa PDF nguồn.

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

Tập có 126 câu hỏi và đáp án được đối chiếu trực tiếp từ PDF; chỉ chấm độ phủ trích dẫn trang và nguồn trong chế độ local sparse/no-LLM. Không coi page-hit là answer accuracy. Kết quả trong `reports/` là runtime output, không nằm trong ZIP.

## 5. Xử lý lỗi và giới hạn

| Tình huống | Kiểm tra |
|---|---|
| `not_ready` | Rebuild index; so sánh checksum PDF và manifest |
| Thiếu model OCR | Kiểm tra `OCOP_EASYOCR_MODEL_DIR` và `OCOP_VIETOCR_WEIGHTS` |
| OCR lỗi hoặc bảng trống | Kiểm tra checkpoint, trang bị quarantine để rà soát source PDF |
| Truy vấn tự rebuild | Giữ DPI khớp bản index đã build |
| Kết quả thiếu chứng cứ | Kiểm tra source scope, năm pháp lý, các trạng thái `needs_review` |
| Dense/Qdrant không có | Đây là tùy chọn; đừng gọi kết quả local sparse là hybrid |
| Frontend thiếu package | Cài Node/npm và chạy `npm ci` khi có mạng |

## 6. Trạng thái kiểm chứng

Các số liệu retrieval baseline được ghi nhận trong [đánh giá](EVALUATION.md). Kết quả OCR mới cần được đo bằng benchmark có nhãn ở [hướng dẫn OCR](PDF_EXTRACTION.md); pytest hoặc số lượng text trích xuất không chứng minh OCR chính xác.

## 7. Vận hành trên tập mẫu (Sample Corpus) & Chế độ Debug API

Theo thiết kế an toàn sản xuất (AGENTS.md, SYSTEM.md), API công khai từ chối phục vụ tập dữ liệu có trạng thái `partial_debug_not_production` (HTTP 409) nhằm đảm bảo không rò rỉ dữ liệu chưa hoàn chỉnh lên môi trường chính thức.

Khi làm việc hoặc kiểm thử trên tập mẫu rút gọn (như `D:/AgentAI/OCOP-RAG/ocop-work-sample`), sử dụng ứng dụng debug chuyên dụng `create_debug_app` với tham số tường minh `allow_partial_debug=True`:

```python
# Khởi tạo debug server từ Python/script
from pathlib import Path
from backend.api.ocop_debug import create_debug_app
import uvicorn

app = create_debug_app(Path("D:/AgentAI/OCOP-RAG/ocop-work-sample"), allow_partial_debug=True)
uvicorn.run(app, host="127.0.0.1", port=8000)
```

Ví dụ truy vấn API debug qua `curl`:
```bash
curl -X POST http://127.0.0.1:8000/api/ocop/query \
  -H "Content-Type: application/json" \
  -d '{"query": "sản phẩm HANA do chủ thể nào sản xuất?", "retrieval_mode": "hybrid", "use_llm": false}'
```
