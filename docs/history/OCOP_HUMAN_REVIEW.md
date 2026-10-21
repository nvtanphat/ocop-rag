# Duyệt ứng viên OCOP

Mở mục **Người duyệt** trong giao diện OCOP. Backend đọc corpus tại `OCOP_ROOT`
(mặc định là thư mục dự án). Chỉ dùng corpus công khai trong registry đã khóa.
Không đưa hồ sơ riêng vào hàng đợi hoặc index công khai.

Chọn P1 trước: điểm, sao và hiệu lực. P2 gồm trách nhiệm, giấy tờ đầu vào và
các cảnh báo chất lượng; P3 là cấu trúc và danh mục còn lại. Mỗi mục hiển thị
giá trị máy trích, nguyên văn, trang, bbox, SHA và ảnh crop 300 DPI. Ảnh chỉ được
render từ PDF có SHA khớp registry và citation; mở cả trang PDF để đọc ngữ cảnh,
điều kiện và chú thích. Crop được lưu trong runtime, không sửa PDF.

- **Xác nhận giá trị máy trích**: khẳng định và mọi thuộc tính khớp nguồn, đúng chủ thể,
  phạm vi, phiên bản và điều kiện áp dụng. Có citation chưa đủ để xác nhận.
- **Loại ứng viên**: nguồn không chứng minh khẳng định, parser gán sai vai trò,
  hoặc không đủ thông tin để dùng như thông tin đã xác minh. Ghi lý do.
- **Ghi giá trị sửa**: người duyệt đọc được giá trị đúng từ nguồn. Nhập giá trị
  và ghi chú căn cứ; hệ thống giữ nguyên OCR trong `machine_candidate` và
  knowledge, lưu giá trị sửa riêng như khẳng định của người duyệt.

Nhập tên người duyệt, đánh dấu đã đọc chứng cứ rồi gửi từng mục. Không có nút
duyệt hàng loạt. Mã truy cập được cấp qua `OCOP_REVIEW_TOKEN` nếu backend bật
yêu cầu này. Mã không được lưu trong ledger.

Các mục **cần duyệt riêng** dẫn tới evidence unit và hai đầu cạnh. Duyệt thực
thể không tự duyệt evidence unit. Một evidence unit được xác nhận cho toàn bộ
nguyên văn và các span của nó; chỉ approve khi đã đọc toàn bộ, hoặc reject nếu
không đáng tin. Sửa khẳng định nghiệp vụ thay vì sửa nguyên văn evidence unit.
Thực thể chỉ `verified` khi quyết định của chính nó và mọi evidence unit còn
khớp. Cạnh còn cần cả hai đầu đã `verified`. Trạng thái chờ giải thích phần
phụ thuộc chưa được duyệt; dùng các liên kết để mở từng mục.

Duyệt EvidenceUnit xác nhận người duyệt đã đối chiếu **nguồn và các vùng trích
dẫn của toàn unit**: PDF/SHA, trang, bbox và nguyên văn OCR được lưu đúng như
máy đã đọc. Nó không xác nhận mọi diễn giải hoặc mọi con số của unit. Nếu OCR
đọc sai nhưng vùng nguồn đúng, ghi rõ lỗi OCR trong ghi chú, rồi dùng `correct`
trên từng khẳng định nghiệp vụ cần sửa. Nếu vùng nguồn sai hoặc không xác định
được, reject unit. Không khẳng định nghiệp vụ nào tự verified từ quyết định
duyệt unit; mỗi khẳng định vẫn cần quyết định riêng.

**Cần duyệt lại** nghĩa là label, thuộc tính hoặc quote/bbox/SHA đã thay đổi.
Quyết định cũ còn trong lịch sử nhưng không còn hiệu lực. Tải lại mục, đối chiếu
nguồn và gửi quyết định mới; không chép hash cũ. Quyết định mới nhất theo thời
gian thay thế quyết định trước, không xóa lịch sử.

Bật **Hiện cả mục đã duyệt** để xem hoặc thay thế quyết định. Nếu một ID mới
thay ID cũ sau trích xuất lại, hàng đợi đánh dấu cùng loại/trang nguồn cần
duyệt lại; không chuyển quyết định cũ sang ID mới. Đây là cờ kiểm tra, không
phải phép ghép để tự xác minh. Khi sửa nhiều thuộc tính, dùng **Thêm giá trị
sửa** cho từng thuộc tính rồi gửi một quyết định. Quyết định `correct` mới
phải chứa đủ các giá trị sửa muốn giữ, kể cả từ quyết định cũ; có thể xem
quyết định gần nhất ngay trong mục. `approve` xác nhận giá trị OCR gốc và
không giữ các giá trị sửa của quyết định trước.

## CLI và dữ liệu runtime

```powershell
python tools/cli.py review stats --root C:/path/to/runtime-root
python tools/cli.py review queue --root C:/path/to/runtime-root
# Thêm --render để tạo trước mọi crop; mặc định API render khi mở mục.
python tools/cli.py review decide --root C:/path/to/runtime-root --target-id ID --content-hash HASH --decision approve --reviewer "Tên người duyệt" --notes "Đã đối chiếu trang"
```

Với `correct`, thêm `--correction-file` trỏ tới JSON, ví dụ
`{"properties":{"points_candidate":3}}`. Đây chỉ là ví dụ cú pháp, không phải
quyết định cho corpus thật. Ledger append-only:
`data/review/ocop_review_decisions.jsonl`; queue xuất tại
`data/review/ocop_review_queue.jsonl`; crop:
`data/runtime/ocop/review_crops`. Các thư mục này không đóng gói cùng mã nguồn.
Không sửa ledger bằng tay. Mỗi lần gửi quyết định, graph được build lại qua
builder hiện có; nếu build lỗi, quyết định đã ghi vẫn còn, chạy lệnh build
chính thức để áp lại. Knowledge OCR không bị ghi đè.

API: `GET /api/ocop/review/stats`, `GET /queue`, `GET /items/{id}`,
`GET /items/{id}/crops/{index}`, `POST /decisions`, cùng prefix review.
Test vòng duyệt chỉ dùng PDF tổng hợp; không có quyết định của agent trên
corpus thật.
