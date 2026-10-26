# Kiến trúc OCOP GraphRAG

Hệ thống có một corpus đang hoạt động. `ocop_main.py` phục vụ API và `frontend/dist`; Vite chỉ dùng khi phát triển, proxy `/api` tới backend cổng 8000.

## Nguồn và dẫn xuất

- `data/raw/ocop`: PDF gốc bất biến. Registry và source lock trong `configs/` xác định danh tính, đường dẫn và SHA-256.
- `ocop_contracts`: hợp đồng nguồn, trang, EvidenceUnit, dataset OCR, khoá tiến trình.
- `ocr/ocop_ocr`: đọc PDF/OCR và xuất dataset độc lập. RAG chỉ đọc dataset, không tự chạy OCR.
- `ai_core/processing/ocop`: tạo EvidenceUnit và ứng viên tri thức. Mỗi span giữ trang, bbox và SHA nguồn; ứng viên OCR không được nâng thành dữ liệu verified tự động.
- `ai_core/graph/ocop`: dựng `nodes.jsonl`, `edges.jsonl`, `manifest.json`, kiểm ontology/căn cứ, snapshot và quyết định review. Bản ghi thất bại không được dùng trong truy xuất công khai.
- `ai_core/retrieval/ocop`: chunk theo cấu trúc, chuỗi cha, BM25, dense tùy chọn, RRF và rerank có ngân sách. Index giữ phiên bản tri thức và graph.
- `ai_core/system/pipeline.py`: kiểm tính nhất quán, dựng dẫn xuất trong thư mục tạm rồi hoán đổi dưới khoá. Thất bại không được giả thành bản dựng thành công. Dựng, khoá và phát hành luôn băm lại byte của PDF; các endpoint `/health`, `/criteria`, `/products`, `/query` dùng lại mã băm khi kích thước và thời điểm sửa của tệp không đổi, và băm lại ngay khi một trong hai thay đổi.

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
| GET | `/graph/subgraph` | Vùng lân cận đã qua kiểm tra của một nút hoặc của các thực thể mà một `evidence_unit_id` hỗ trợ |
| POST | `/query` | `AskRequest` → `AgentResponse` |

`/graph/subgraph` nhận `node_id` (lặp được) hoặc `evidence_unit_id`, `hops` (0–2) và `limit` (≤150). Nó dùng cùng bộ duyệt đồ thị với agent, nên chỉ trả nút/cạnh đạt kiểm tra, bỏ bản gốc chưa kiểm dành cho reviewer, và mỗi nút giữ trang, bbox, SHA-256 của bằng chứng. Thiếu đồ thị trả `no_graph`; không có nút khớp trả `no_seed`; đồ thị lệch phiên bản hoặc thiếu kiểm tra trả HTTP 503 thay vì dữ liệu cũ.

## Hồ sơ truy xuất

`OCOP_RETRIEVAL_PROFILE` quy định bản triển khai phục vụ gì:

- `sparse` (mặc định): chỉ BM25. Yêu cầu `retrieval_mode` là `dense` hoặc `hybrid` bị từ chối bằng HTTP 422 thay vì âm thầm trả kết quả BM25.
- `hybrid`: cần `sentence-transformers`, `qdrant-client`, chỉ mục dense đã dựng và Qdrant truy cập được. Thiếu bất kỳ mục nào, `/health` báo `not_ready` kèm danh sách `retrieval_profile.missing` và `/query` trả 503.

## Phiên hội thoại

Mặc định phiên nằm trong bộ nhớ một tiến trình (TTL 1 giờ, tối đa 512 phiên). Với nhiều worker trên một máy hoặc cần giữ phiên qua lần khởi động lại, đặt `OCOP_SESSION_STORE=sqlite`: mọi lần cập nhật là một giao dịch `BEGIN IMMEDIATE` nên các lượt đồng thời không ghi đè nhau. Nhiều máy cần kho mạng triển khai cùng giao diện `get/save`.

Request hỏi đáp gồm `query`, `session_id`, `retrieval_mode`, `use_llm`; không nhận trường thừa. Response giữ nguyên citation, bao gồm `source_id`, `pdf_page`, `bbox`, `evidence_unit_id`, `source_sha256` và các span liên quan. HTTP 503 có thông báo hạ tầng được giới hạn để không lộ bí mật.

Hai endpoint reference đọc `knowledge/verified_criteria.jsonl` và `verified_products.jsonl` do server quản lý. Chỉ trả trường cho phép từ bản ghi `verified`/`human_verified`, `visibility=public`, đúng corpus active, không mang tenant/hồ sơ. Citation phải khớp EvidenceUnit đã xác minh, span và PDF khoá SHA; nhãn chứa điểm/sao phải có hỗ trợ số tương ứng. Thiếu dữ liệu hoặc corpus chưa nhất quán: `status=no_verified_data`, `items=[]`; UI hiện “Chưa có dữ liệu xác minh”. Chúng không biến OCR candidates thành quy tắc đánh giá.

## Frontend

Giao diện React (Vite) là một ứng dụng một trang, bố cục fluid: nền phong cảnh, thanh trên, rail điều hướng và vùng chính. Màn hình gồm chat, thư viện văn bản, tiêu chí, sản phẩm và lịch sử phiên. Chat có cột phải (hành động nhanh, tài liệu nguồn, sản phẩm đã xác minh) và hai bảng thay thế cột phải: trình xem PDF và đồ thị dẫn chứng.

| Thư mục | Vai trò |
| --- | --- |
| `src/api/client.ts` | Client duy nhất gọi `/api/ocop/*`; timeout, lỗi HTTP và mất kết nối đều thành lỗi hiển thị, không có dữ liệu thay thế |
| `src/app/Workspace.tsx` | Trạng thái phiên, dữ liệu và điều hướng; đồng bộ `data-view`, `dark`, `pdf-open`, `graph-open` lên `body` cho stylesheet |
| `src/components/` | Header, rail, cột phải, phân trang, biểu tượng, nền |
| `src/features/chat` | Hội thoại; Markdown không cho raw HTML; marker hợp lệ mở citation của chính câu trả lời |
| `src/features/documents` | Danh mục nguồn từ `/sources`, nhóm theo loại, lọc theo phạm vi, dạng lưới/danh sách |
| `src/features/references` | Tiêu chí và sản phẩm từ `/criteria`, `/products`, xuất CSV; dùng chung một view |
| `src/features/pdf` | Ảnh trang từ `evidence.png` với đúng SHA và bbox, điều hướng trang, thu phóng, bật/tắt vùng trích dẫn, mở PDF gốc đúng trang |
| `src/features/graph` | Tab "Dẫn chứng": liên kết câu hỏi → nguồn trích dẫn thực tế. Tab "Quan hệ tri thức": vùng lân cận từ `/graph/subgraph` quanh một đoạn bằng chứng hoặc nút, phân biệt nút đã được người duyệt với nút chỉ đạt kiểm tra tự động, mở được PDF tại vị trí của từng nút; không suy diễn quan hệ pháp lý |
| `src/styles/workspace.css` | Stylesheet duy nhất của giao diện, gồm giao diện sáng/tối |

Tài liệu, sản phẩm, tiêu chí, trang và vị trí citation đều đến từ API; FE chỉ giữ nhãn giao diện. Thiếu dữ liệu xác minh thì hiện trạng thái rỗng, không hiện điểm/sao. Truy vết công cụ lấy từ response thực tế.

Review thực hiện qua CLI; không có API hay màn hình ghi quyết định review. Xem [RUNBOOK](RUNBOOK.md). Các quyết định nền tảng nằm trong [ADR](adr/README.md).
