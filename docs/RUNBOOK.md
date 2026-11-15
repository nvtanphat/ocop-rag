# Vận hành

## Khởi động

Từ repo đã cài dependencies, một lệnh chạy cả FE build và API:

```powershell
.\run.ps1
```

Backend phục vụ http://127.0.0.1:8000. Dùng `-Port` để chọn cổng; `-BackendOnly` bỏ build FE khi đã có `frontend/dist`. Ctrl+C dừng backend, không có tiến trình Vite ẩn còn lại.

Docker cũng phục vụ cả hai từ một container:

```powershell
docker compose up --build -d backend
```

Mặc định image chỉ phục vụ truy xuất sparse. Để phục vụ hybrid, dựng với `OCOP_PROFILE=hybrid` và chạy Qdrant cùng chỉ mục dense:

```powershell
$env:OCOP_PROFILE = "hybrid"
docker compose --profile stores up --build -d
```

Kiểm tra `GET /api/ocop/health`: `retrieval_profile.ready` phải là `true`; nếu không, `retrieval_profile.missing` nêu dependency, chỉ mục hoặc kết nối Qdrant còn thiếu.

PDF gốc được mount read-only. Dẫn xuất ở `data/processed` cần quyền ghi cho UID 10001 của container. Dataset OCR được mount read-only từ `OCOP_OCR_DATASET` hoặc `data/ocr-dataset`. Dừng bằng:

```powershell
docker compose stop backend
```

### Quản lý container và sự cố Docker khi thiếu tài nguyên

Trên môi trường phát triển cục bộ, Docker daemon hoặc WSL có thể tự động tắt các container lưu trữ (đặc biệt là `ocop-qdrant`) khi máy bị thiếu RAM hoặc phân vùng ổ C bị đầy.

> [!WARNING]
> Khi `ocop-qdrant` bị tắt, hệ thống không báo lỗi hay crash ứng dụng mà tự động kích hoạt cơ chế suy thoái mềm (fallback), âm thầm chuyển về tìm kiếm từ khoá BM25. Khi đó các yêu cầu `hybrid` hoặc `rerank` sẽ bị suy giảm chất lượng mà không có cảnh báo rõ ràng.

1. **Kiểm tra trạng thái container**:
   ```powershell
   docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
   ```
   Đảm bảo `ocop-qdrant` và `ocop-graphrag-neo4j-1` luôn ở trạng thái `Up`.

2. **Bật lại container lưu trữ**:
   - Khởi động lại riêng Qdrant:
     ```powershell
     docker compose up -d qdrant
     ```
   - Khởi động lại toàn bộ cụm lưu trữ (Qdrant và Neo4j):
     ```powershell
     docker compose --profile stores up -d
     ```
   - Trường hợp ổ đĩa C bị đầy, chỉ dọn image và build cache không dùng:
     ```powershell
     docker image prune -f
     docker builder prune -f
     ```
     Không dùng `docker system prune`: lệnh này xoá cả container đang dừng, kể cả `ocop-qdrant` hoặc `ocop-graphrag-neo4j-1` vừa tự tắt. Dữ liệu trong volume vẫn còn nhưng phải tạo lại container bằng `docker compose --profile stores up -d`.

3. **Tắt backend container khi chạy đo lường đánh giá**:
   Khi chạy các script đánh giá (`tools/evaluate_*.py`, `tools/cli.py evaluate`) trên máy host, phải dừng container backend để giải phóng bộ nhớ RAM, tránh tranh chấp CPU và khóa tải mô hình cục bộ:
   ```powershell
   docker stop ocop-graphrag-backend-1
   ```
   (hoặc `docker compose stop backend`). Sau khi đo xong, khởi động lại container backend bằng `docker compose up -d backend`.

## Chuẩn bị corpus

PDF, registry và lock phải khớp nhau. Dataset OCR phải hoàn chỉnh, đủ mọi trang nguồn, đúng schema/digest/SHA; không sửa manifest để đánh dấu dữ liệu thiếu trang thành hoàn chỉnh. Xem [OCR](../ocr/README.md) để tạo và duyệt dataset.

Sau khi đặt dataset hoàn chỉnh vào `data/ocr-dataset`, dựng không dùng LLM và khởi động:

```powershell
.\run.ps1 -OcrDataset data/ocr-dataset
```

Chỉ dựng corpus, không chạy server:

```powershell
python tools/cli.py run --ocr-dataset data/ocr-dataset --no-semantic-extract --build-only
```

Lệnh này đọc dataset OCR độc lập, không thực hiện OCR. Muốn dựng lại mọi dẫn xuất, thêm `--refresh`; source PDF không được sửa. Phạm vi mã làm đổi phiên bản được mô tả tại [vân tay mã nguồn](DEVELOPMENT.md#vân-tay-mã-nguồn); không phải mọi thay đổi runtime đều yêu cầu dựng lại.

### Dựng lại từ văn bản OCR đã duyệt

Văn bản đã duyệt nằm trong một Markdown duy nhất (`data/ocr-review/ocop-ocr-reviewed.md`, mỗi trang một mục `## <source_id> — trang N`, bảng ngay dưới `**Bảng N**`). Một lệnh nạp vào dataset rồi dựng lại; nạp lặp lại với cùng file không đổi gì:

```powershell
python tools/cli.py run --ocr-dataset data/ocr-dataset --reviewed-text data/ocr-review/ocop-ocr-reviewed.md --dense --build-only
```

Bước nạp thay `extracted_text` và ô bảng bằng chữ đã duyệt, giữ chữ OCR gốc (`ocr_extracted_text`, `ocr_text`), `ocr_hash` và bbox, ghép từng dòng đã duyệt với khối OCR nguồn (`line_blocks`) để mọi trích dẫn giữ bbox, và ghi mỗi trang đổi chữ vào `review/corrections.jsonl`. Trang không khớp tập trang của dataset làm lệnh dừng. Bước extraction LLM dùng cache theo nội dung đoạn, nên chỉ đoạn có chữ đổi mới gọi lại API. Sửa dòng md rồi chạy lại đúng lệnh trên là đủ.

Sau bước trích xuất thực thể và quan hệ có một file duy nhất để sửa, tương tự file OCR: xem [Sửa kết quả trích xuất](#sửa-kết-quả-trích-xuất).

Kiểm trạng thái và danh mục lệnh:

```powershell
python tools/cli.py status
python tools/cli.py --help
```

## Bố cục `data/`

Mọi dữ liệu của dự án nằm trong `data/`; phần không dựng lại được tách khỏi phần sinh ra:

| Thư mục | Nội dung | Dựng lại được |
|---|---|---|
| `data/raw/ocop` | PDF nguồn bất biến | không |
| `data/ocr-dataset`, `data/ocr-review` | Markdown OCR và bản đã duyệt | một phần |
| `data/extraction` | file sửa thực thể và quan hệ (`entities-relations.md`) và nhật ký sửa | không |
| `data/evaluations` | bộ gold | không |
| `data/processed/ocop` | `pages`, `knowledge`, `graph`, `index`, `cache` | có |
| `data/models` | trọng số model cục bộ (VietOCR: đặt `OCOP_VIETOCR_WEIGHTS=data/models/vietocr/vgg_transformer.pth`) | không |

Schema graph (loại nút, quan hệ và đầu mút hợp lệ) chỉ khai báo một nơi: `ai_core/graph/ocop/ontology.py`; mô hình không tự thêm loại.

## Đối soát citation

Hỏi một câu có dữ liệu trong corpus. Bấm marker hoặc thẻ nguồn của chính câu trả lời: viewer phải hiển thị đúng `source_id`, trang, evidence ID, bbox và SHA. Bật/tắt highlight rồi mở PDF gốc; fragment phải giữ trang đã chọn. Ảnh evidence phải trả PNG từ PDF khoá nguồn, không phải thumbnail minh hoạ.

Kiểm `/api/ocop/health`, `/sources`, `/criteria`, `/products` bằng trình duyệt hoặc OpenAPI tại `/docs`. Danh sách reference rỗng có trạng thái `no_verified_data` là thiếu dữ liệu xác minh, không phải lý do đưa OCR candidates lên thành verified. Không dùng dữ liệu chưa xác minh để công nhận sao/điểm.

## Sửa kết quả trích xuất

Sau khi dựng xong, xuất file để sửa (một lệnh, không có bước duyệt):

```powershell
python tools/cli.py graph export-extraction
```

File `data/extraction/entities-relations.md` liệt kê thực thể và quan hệ dùng được theo từng trang (`## <source_id> — trang N`): `[Norm] <mã> | nhãn` và `[GOVERNS] <mã> <đầu> -> <cuối>`. Sửa chữ sau dấu `|` để sửa nhãn, xóa cả dòng để bỏ thực thể (cùng các quan hệ của nó) hoặc bỏ quan hệ. Dựng lại bằng `python tools/cli.py graph refresh-graph` (chỉ dựng lại graph) hoặc `run`; hệ thống không đổi câu trích, trang, bbox và SHA nguồn, giữ nhãn gốc trong `properties.extracted_label` và ghi mỗi thay đổi vào `data/extraction/corrections.jsonl`. Dòng nào chưa từng được xuất thì không bị coi là đã xóa.

Trạng thái kiểm tra của mỗi nút và cạnh chỉ có hai giá trị tự động: `passed` (câu trích nằm nguyên văn trong đơn vị bằng chứng, đúng loại đầu mút) hoặc `failed`. Nút và cạnh `failed` không được dùng khi trả lời và không vào Neo4j.

Xuất bản graph hiện hành sang Neo4j (idempotent, theo snapshot bất biến, ghi trạng thái vào manifest của graph): `docker compose --profile stores up -d neo4j`, sau đó `python tools/cli.py graph publish-neo4j` (đọc `NEO4J_PASSWORD` từ môi trường hoặc `.env`). Dựng lại graph xoá trạng thái này, tức bản trên Neo4j đã cũ: chạy lại lệnh.

Danh sách cho `/criteria` và `/products`: `python tools/cli.py graph export-references` ghi `knowledge/verified_criteria.jsonl` và `verified_products.jsonl` từ graph hiện hành. Bước làm mới index và pipeline hệ thống tự chạy việc này mỗi khi corpus đổi.

## Quan sát

Mỗi câu hỏi được trả lời để lại một dòng log `ocop.api query {...}` gồm `status`, `intent`, `path` (luồng RAG), `tools`, `mode`, `llm`, `citations`, `claims_accepted`/`claims_rejected`, `total_ms`, `tools_ms`, `generation_ms`. Dòng này không chứa câu hỏi, phiên, câu trả lời hay đoạn trích. Mỗi lần trả 503 để lại `ocop.api unavailable code=… layer=… error=<loại lỗi>` (không có thông điệp lỗi). `OCOP_LOG_LEVEL` đổi mức log (mặc định `INFO`). Chi tiết từng bước của một câu hỏi nằm trong `tool_trace` và `generation_diagnostics` của chính phản hồi.

Span OpenTelemetry (`ocop.agent.ask`, `ocop.agent.tool_dispatch`, `ocop.retrieval.search`, `ocop.llm.*`) chỉ phát khi tiến trình API được cấu hình SDK và exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`); không cấu hình thì chúng không làm gì.

## Xử lý lỗi

| Triệu chứng | Kiểm tra |
| --- | --- |
| FE báo không kết nối được | Backend có chạy, đúng cổng, Vite proxy tới 8000 |
| HTTP 503 hoặc health chưa ready | Dataset đầy đủ, source lock, fingerprint extraction/index/graph, cờ promoting |
| HTTP 422 khi mở evidence | Số trang, thứ tự/bounds bbox, SHA của citation so với PDF |
| Reference rỗng | Chạy `graph export-references`; tệp verified phải đúng corpus index, visibility public, citation khớp EvidenceUnit và PDF khoá SHA |
| LLM không khả dụng | Provider, endpoint, model, key; tắt sinh LLM để tra bằng chứng thuần |
| Graph/index version mismatch | Dựng lại đồng bộ hoặc làm mới index sau khi sửa |

Không log key, nội dung hồ sơ riêng tư hay exception thô ra response. Không xoá file ignored hoặc dữ liệu người dùng để làm test xanh.
