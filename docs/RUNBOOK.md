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

Quyết định duyệt node/cạnh nằm ở `data/review/ocop_review_decisions.jsonl`, gắn với `content_hash`; sau khi dựng lại, quyết định cũ còn hiệu lực với mục có hash không đổi, mục có chữ hoặc bbox đổi quay về chưa duyệt.

Kiểm trạng thái và danh mục lệnh:

```powershell
python tools/cli.py status
python tools/cli.py --help
```

## Đối soát citation

Hỏi một câu có dữ liệu trong corpus. Bấm marker hoặc thẻ nguồn của chính câu trả lời: viewer phải hiển thị đúng `source_id`, trang, evidence ID, bbox và SHA. Bật/tắt highlight rồi mở PDF gốc; fragment phải giữ trang đã chọn. Ảnh evidence phải trả PNG từ PDF khoá nguồn, không phải thumbnail minh hoạ.

Kiểm `/api/ocop/health`, `/sources`, `/criteria`, `/products` bằng trình duyệt hoặc OpenAPI tại `/docs`. Danh sách reference rỗng có trạng thái `no_verified_data` là thiếu dữ liệu xác minh, không phải lý do đưa OCR candidates lên thành verified. Không dùng dữ liệu chưa xác minh để công nhận sao/điểm.

## Review qua CLI

Không có review endpoint hoặc màn hình ghi quyết định. Xem các tham số và thống kê hiện tại:

```powershell
python tools/cli.py review --help
python tools/cli.py review stats
```

`review queue` xuất hàng đợi; `--render` tạo crop từ PDF đã kiểm SHA. Người duyệt đối chiếu trang và vùng bằng chứng trước khi gọi `review decide` với `--target-id`, `--content-hash`, `--decision`, `--reviewer`; chỉ dùng ID/hash thực lấy từ hàng đợi. Quyết định `correct` cần tệp correction hợp lệ. Không sao chép ID/hash của ví dụ vào corpus thật.

Xuất bản graph hiện hành sang Neo4j (idempotent, theo snapshot bất biến, ghi trạng thái vào manifest của graph): `docker compose --profile stores up -d neo4j`, sau đó `python tools/cli.py review publish-neo4j` (đọc `NEO4J_PASSWORD` từ môi trường hoặc `.env`). Dựng lại graph sẽ xoá trạng thái này, tức bản trên Neo4j đã cũ: chạy lại lệnh. `run --neo4j` dựng lại cả corpus và xuất bản graph vừa dựng, không phải graph hiện hành, nên không dùng cho mục đích này.

Danh sách cho `/criteria` và `/products`: `python tools/cli.py review export-references` ghi `knowledge/verified_criteria.jsonl` và `verified_products.jsonl` từ graph hiện hành. Chạy lại sau mỗi lần dựng lại graph hoặc index.

Ledger tại `data/review/ocop_review_decisions.jsonl` chỉ ghi nối tiếp. Duyệt thực thể không tự động duyệt mọi cạnh và bằng chứng. `decide` dựng graph và làm mới index; nếu graph đã đổi nhưng làm mới index lỗi, giữ ledger và chạy `review refresh-index` sau khi khắc phục hạ tầng. Không xoá lịch sử review.

## Xử lý lỗi

| Triệu chứng | Kiểm tra |
| --- | --- |
| FE báo không kết nối được | Backend có chạy, đúng cổng, Vite proxy tới 8000 |
| HTTP 503 hoặc health chưa ready | Dataset đầy đủ, source lock, fingerprint extraction/index/graph, cờ promoting |
| HTTP 422 khi mở evidence | Số trang, thứ tự/bounds bbox, SHA của citation so với PDF |
| Reference rỗng | Chạy `review export-references`; tệp verified phải đúng corpus index, visibility public, citation khớp EvidenceUnit và PDF khoá SHA |
| LLM không khả dụng | Provider, endpoint, model, key; tắt sinh LLM để tra bằng chứng thuần |
| Graph/index version mismatch | Dựng lại đồng bộ hoặc làm mới index sau review |

Không log key, nội dung hồ sơ riêng tư hay exception thô ra response. Không xoá file ignored hoặc dữ liệu người dùng để làm test xanh.
