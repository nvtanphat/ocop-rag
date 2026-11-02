# OCOP GraphRAG

Hệ thống tra cứu tài liệu OCOP với trích dẫn truy ngược về PDF gốc, trang, vùng bằng chứng và mã SHA-256.

Một hệ thống đầu cuối: PDF → dataset OCR → EvidenceUnit → đồ thị và chỉ mục → định tuyến công cụ → kiểm chứng claim → API FastAPI và giao diện React.

| Việc cần làm | Tài liệu chính |
| --- | --- |
| Cài dependencies, chạy test và phát triển | [DEVELOPMENT](docs/DEVELOPMENT.md) |
| Khởi động bằng PowerShell hoặc Docker, kiểm tra dịch vụ | [RUNBOOK](docs/RUNBOOK.md#khởi-động) |
| Chọn profile truy xuất, mô hình và biến môi trường | [CONFIGURATION](docs/CONFIGURATION.md) |
| Hiểu luồng hỏi đáp, API và frontend | [ARCHITECTURE](docs/ARCHITECTURE.md) |
| Đo chất lượng và đọc kết quả | [EVALUATION](docs/EVALUATION.md) |
| Tra thuật ngữ và quyết định thiết kế | [GLOSSARY](GLOSSARY.md), [ADR](docs/adr/README.md) |
| Quy trình OCR độc lập | [OCR](ocr/README.md) |

Quy tắc sửa mã và bảo toàn nguồn: [AGENTS.md](AGENTS.md).

Repo lưu dataset OCR đã xử lý, bản trích xuất có thể sửa, pages, knowledge, index và snapshot graph đang hoạt động. File graph lớn được lưu bằng Git LFS: cài Git LFS trước khi clone, hoặc chạy `git lfs install` rồi `git lfs pull` nếu đã clone. Dữ liệu được giữ nguyên byte để bảo toàn các digest nguồn và OCR. Cache, log, snapshot cũ, trạng thái chạy và trọng số model OCR không được đưa vào Git. Khi cập nhật graph, thêm rõ thư mục snapshot mới đang được manifest tham chiếu bằng `git add -f data/processed/ocop/graph/snapshots/<graph_version>`.

Dữ liệu lưu trong Qdrant/Neo4j nằm ngoài các file này; cần dựng lại hoặc xuất bản vào các dịch vụ tương ứng theo [RUNBOOK](docs/RUNBOOK.md).
