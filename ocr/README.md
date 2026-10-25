# OCOP OCR

Dự án độc lập tạo dataset trang từ PDF khoá nguồn cho RAG. Package `ocop_contracts` cung cấp schema, kiểm hash và khoá tiến trình; OCR không import `ai_core`.

## Sử dụng

Sau khi cài dependencies theo [DEVELOPMENT](../docs/DEVELOPMENT.md), xem các lệnh:

```powershell
python -m ocop_ocr run --help
python -m ocop_ocr export --help
python -m ocop_ocr import --help
python -m ocop_ocr status --help
```

Tạo dataset đầy đủ ở vị trí mặc định, với model OCR đã được chuẩn bị cục bộ:

```powershell
python -m ocop_ocr run --dataset data/ocr-dataset --workers 3
```

PDF và registry/lock là đầu vào bất biến. Chế độ `--without-ocr` chỉ dùng cho tài liệu native text; không được coi trang scan chưa đọc là đã được OCR. `--page SOURCE_ID:PAGE` chọn một số trang để kiểm tra riêng; dataset thiếu trang không được nạp làm corpus RAG hoàn chỉnh.

## Duyệt chữ và bảng

`export` tạo Markdown và ảnh từ đúng PDF/SHA. Chỉnh chữ hoặc ô bảng trong `review/<source_id>/p###.md`, giữ ID khối, hàng/cột và front matter. Sau khi đối chiếu ảnh, đổi trạng thái thành `da_duyet`; `import` kiểm toàn bộ trước khi ghi corrections. Ký tự `|` và xuống dòng trong ô dùng HTML entity; ô trống có marker riêng.

Không sửa có thể import lại mà không tạo thay đổi. SHA gốc, geometry hoặc schema sai bị từ chối. Reader từ chối dataset còn `.pending-import.json`; chạy lại import để phục hồi giao dịch. Corrections là nhật ký nối tiếp.

Dataset giữ chữ OCR gốc, bbox, SHA và trạng thái duyệt chữ. Duyệt chữ OCR không tự xác minh thực thể, quan hệ hoặc giá trị điểm/sao.

## Vận hành và kiểm thử

Mỗi worker dùng model cục bộ và giới hạn luồng Torch. Hai thao tác có đỉnh bộ nhớ lớn, CRAFT detection và Paddle layout tuỳ chọn, dùng khoá dùng chung; tiến trình chết tự nhả khoá. Không xoá file khoá khi worker còn hoạt động. `OCOP_OCR_PEAK_LOCK` cho phép chọn vị trí khoá giữa các tiến trình trên cùng máy.

`status` đọc cả trạng thái đang chạy/chưa công bố; chạy lại `run` dùng cache trang đã xong. Không đổi DPI hay ngưỡng để làm một ca lỗi có vẻ đạt.

```powershell
python -m pytest ocr/tests -q
ruff check ocop_contracts ocr
```

RAG đọc dataset đầy đủ bằng `tools/cli.py run --ocr-dataset ...`; hướng dẫn ở [RUNBOOK](../docs/RUNBOOK.md). Không có đường chạy OCR riêng bên trong runtime hỏi đáp.
