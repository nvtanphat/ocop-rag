# Kiến trúc OCOP GraphRAG

Hệ thống có một corpus đang hoạt động. `ocop_main.py` phục vụ API và `frontend/dist`; Vite chỉ dùng khi phát triển, proxy `/api` tới backend cổng 8000.

## Nguồn và dẫn xuất

- `data/raw/ocop`: PDF gốc bất biến. Registry và source lock trong `configs/` xác định danh tính, đường dẫn và SHA-256.
- `ocop_contracts`: hợp đồng nguồn, trang, EvidenceUnit, dataset OCR, khoá tiến trình.
- `ocr/ocop_ocr`: đọc PDF/OCR và xuất dataset độc lập. RAG chỉ đọc dataset, không tự chạy OCR.
- `ai_core/processing/ocop`: tạo EvidenceUnit và ứng viên tri thức. Mỗi span giữ trang, bbox và SHA nguồn; ứng viên OCR không được nâng thành dữ liệu verified tự động.
- `ai_core/graph/ocop`: dựng `nodes.jsonl`, `edges.jsonl`, `manifest.json`, kiểm ontology/căn cứ, snapshot và quyết định review. Bản ghi thất bại không được dùng trong truy xuất công khai.
- `ai_core/retrieval/ocop`: chunk theo cấu trúc, chuỗi cha, BM25, dense tùy chọn, RRF và rerank có ngân sách. Index giữ phiên bản tri thức và graph.
- `ai_core/system/pipeline.py`: kiểm tính nhất quán, dựng dẫn xuất trong thư mục tạm rồi hoán đổi dưới khoá. Thất bại không được giả thành bản dựng thành công.

## Hỏi đáp

`OcopAgent` hiểu hội thoại và ý định miền, lập DAG công cụ, thực thi có giới hạn, chấm độ phủ, khôi phục có giới hạn và ghép câu trả lời. Router/LLM chỉ chọn trong registry; mặc định tối đa năm lần gọi, kể cả khôi phục. Một năm lịch sử không được âm thầm thay quyết định đã ghim.

Nguồn được ghép theo cửa sổ liên quan đến câu hỏi. Marker hợp lệ chỉ chứng minh liên kết trích dẫn; cổng claim kiểm thêm số/điểm/sao và căn cứ trong đoạn trích. Nguồn chưa duyệt có thể được hiển thị với nhãn chưa xác minh theo ADR-009; không vì vậy mà công nhận điểm/sao sản phẩm.

Phiên chỉ lưu ngữ cảnh hội thoại đã giới hạn và che định danh. Quyền riêng tư chỉ đến từ `AuthContext` phía server; request công khai không nhận tenant, hồ sơ hay rule do client cung cấp. Index public không chứa hồ sơ riêng tư.

## API giao diện

| Method | Đường dẫn dưới `/api/ocop` | Nội dung |
| --- | --- | --- |
| GET | `/health` | Trạng thái backend, corpus và tính nhất quán |
| GET | `/sources` | Nguồn được đăng ký và số trang đã xử lý |
| GET | `/sources/{source_id}/pdf` | PDF gốc theo registry, hiển thị trang qua fragment `#page=N` |
| GET | `/sources/{source_id}/pages/{page}/evidence.png` | Ảnh trang với `box`, `context`, `sha`, `dpi`, `crop` được kiểm |
| GET | `/criteria` | Tiêu chí verified công khai theo corpus active |
| GET | `/products` | Sản phẩm verified công khai theo corpus active |
| POST | `/query` | `AskRequest` → `AgentResponse` |

Request hỏi đáp gồm `query`, `session_id`, `retrieval_mode`, `use_llm`; không nhận trường thừa. Response giữ nguyên citation, bao gồm `source_id`, `pdf_page`, `bbox`, `evidence_unit_id`, `source_sha256` và các span liên quan. HTTP 503 có thông báo hạ tầng được giới hạn để không lộ bí mật.

Hai endpoint reference đọc `knowledge/verified_criteria.jsonl` và `verified_products.jsonl` do server quản lý. Chỉ trả trường cho phép từ bản ghi `verified`/`human_verified`, `visibility=public`, đúng corpus active, không mang tenant/hồ sơ. Citation phải khớp EvidenceUnit đã xác minh, span và PDF khoá SHA; nhãn chứa điểm/sao phải có hỗ trợ số tương ứng. Thiếu dữ liệu hoặc corpus chưa nhất quán: `status=no_verified_data`, `items=[]`; UI hiện “Chưa có dữ liệu xác minh”. Chúng không biến OCR candidates thành quy tắc đánh giá.

## Frontend

`src/api/client.ts` là client duy nhất. Timeout, lỗi HTTP và mất kết nối đều hiển thị lỗi; không trả dữ liệu giả. `app/Workspace.tsx` quản lý phiên và dữ liệu; `features/chat`, `documents`, `references`, `pdf` render các phần tương ứng. Chỉ có một `components/TopHeader.tsx`.

Câu trả lời render Markdown không cho raw HTML. Marker hợp lệ mở citation của chính câu trả lời đó, không dùng map toàn cục có thể bị lượt sau ghi đè. EvidenceViewer gửi đúng SHA và bbox tới endpoint ảnh; liên kết PDF gốc giữ đúng trang. Tiêu chí và sản phẩm dùng cùng view reference, không có bộ dữ liệu FE riêng. Truy vết công cụ lấy từ response thực tế.

Review thực hiện qua CLI; không có API hay màn hình ghi quyết định review. Xem [RUNBOOK](RUNBOOK.md). Các quyết định nền tảng nằm trong [ADR](adr/README.md).
