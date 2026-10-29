# Phát triển

Python 3.11+, Node.js 22.14+; cài package hợp đồng, OCR và ứng dụng từ gốc repo:

```powershell
python -m pip install -e ./ocop_contracts -e ./ocr -e ".[agent,persistence,dev]"
Push-Location frontend
npm ci
Pop-Location
```

OCR engines/model là dependencies của dự án OCR; dataset là đầu vào độc lập của RAG. Không cần model hoặc dịch vụ ngoài để chạy test offline.

## Kiểm thử

```powershell
python tools/cli.py --help
python -m pytest -q
ruff check .
Push-Location frontend
npm test
npm run build
npx tsc --noEmit
Pop-Location
```

`pytest` bao gồm `tests/ocop` và `ocr/tests`. Các nhóm test ứng dụng: `api`, `retrieval`, `graph`, `orchestration`, `extraction`, `contracts`, `privacy`. Fixture dùng chung nằm trong `tests/fixtures`. Giữ các assertion về provenance, điểm/sao, quyền riêng tư, phiên bản ghim và ngân sách tool. Không thay chúng bằng kiểm tra chuỗi mã nguồn hoặc nới điều kiện để tránh lỗi.

Test API dùng `backend.api.ocop_main.app` với fixture cô lập corpus, phiên và dependencies. Test không đọc `.env` cá nhân, không gọi model/mạng thật; fixture chặn kết nối ngoài trong bộ ứng dụng. Test OCR giữ skip khi dependency tuỳ chọn không có. Vitest dùng fake fetch/timer, render citation an toàn; build luôn chạy TypeScript trước Vite. CI chạy Ruff đầy đủ, cả hai bộ Python và test/build frontend.

## Frontend

`src/api/client.ts` là nơi duy nhất gọi API; cấu trúc thư mục xem [ARCHITECTURE](ARCHITECTURE.md). Nhãn giao diện là hằng; tài liệu, sản phẩm, điểm/sao, quan hệ và vị trí citation phải đến từ API.

Khi cần HMR, chạy backend cổng 8000 và Vite ở terminal riêng:

```powershell
Push-Location frontend
npm run dev
Pop-Location
```

Proxy `/api` đi tới backend; bản production do backend phục vụ trực tiếp. Không thêm endpoint khác miền OCOP hoặc đường gọi trực tiếp LLM từ FE.

## Thay đổi mã và dữ liệu

Đọc AGENTS.md, GLOSSARY và ADR trước khi sửa. Python snake_case, React component PascalCase, thư mục lowercase. Dùng `git mv` khi đổi tên, sửa import và docs cùng lúc. Không đổi public contract hoặc hành vi miền mà chưa trao đổi với chủ repo.

Tool mới phải được đăng ký ở `capabilities.py`, có logic dispatch và test qua interface công khai. LLM không có quyền đăng ký tên tool, vượt ngân sách hoặc cấp AuthContext. Quy tắc đánh giá phải đến từ nguồn verified khớp corpus active, không nhận từ client hoặc prompt.

Không sửa/đổi tên PDF gốc, không tái khoá nguồn để che thay đổi. Dữ liệu nguồn mới cần quy trình phê duyệt registry/lock riêng; sau đó dựng lại dataset và corpus. Entity catalog sinh từ registry/graph, không viết cứng tên văn bản/sản phẩm trong router. Từ vựng ở `ocop_language.yaml`; ngưỡng và ngân sách ở `ocop_retrieval.yaml`/`ocop_models.yaml`.

Commit nhỏ theo conventional commits; chỉ stage đường dẫn đã sửa. Không commit `.env`, dữ liệu riêng tư, dẫn xuất runtime hoặc báo cáo sinh tự động. Xem [EVALUATION](EVALUATION.md) trước khi sử dụng bộ giữ riêng.

## Vân tay mã nguồn

Danh sách tệp quyết định phiên bản nằm ngay tại nơi khai báo:

- `VERSION` trong [knowledge_extract.py](../ai_core/processing/ocop/knowledge_extract.py).
- `SCHEMA_REVISION` trong [builder.py](../ai_core/graph/ocop/builder.py).
- `INDEX_VERSION` trong [index_pipeline.py](../ai_core/retrieval/ocop/index_pipeline.py).

Chỉ thay đổi tệp thuộc các danh sách này mới làm đổi vân tay tương ứng. Không
format, sửa comment hoặc dọn mã trong đó khi cần giữ nguyên corpus. Thay mã
runtime ngoài danh sách không tự yêu cầu dựng lại dữ liệu. Kiểm phiên bản và
trạng thái bằng `python tools/cli.py status`; không sửa manifest để bỏ kiểm tra.
