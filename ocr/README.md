# OCOP OCR

Dự án con tạo dữ liệu trang cho RAG. PDF, registry và source lock là đầu vào
bất biến; package `ocop_contracts` chứa model, layout và kiểm SHA dùng chung,
chỉ phụ thuộc Pydantic. OCR không import `ai_core`.

Từ thư mục repo, dùng môi trường OCR có sẵn các model đã được kiểm:

```powershell
python -m pip install --no-deps -e ./ocop_contracts -e ./ocr
python -m pytest -q ocr/tests
```

Không có model hoặc thư viện mới nào được tải bởi thao tác cài `--no-deps` này.
Các ràng buộc dependency hiện giữ từ dự án cha; chưa bổ sung model mới.

Lệnh parser trong bước tách giữ nguyên hành vi:

```powershell
python -m ocop_ocr.pdf_pipeline --help
```

Đầu ra raw của parser chưa phải dataset được duyệt. Lớp chuyển tiếp tại
`ai_core/processing/ocop` dành cho script cũ; mã nguồn OCR chỉ nằm ở đây.

Kiểm chứng việc tách: 22 trang chạy native (OCR tắt) giống hệt PageArtifact
trước tách; đây không thay thế kiểm chứng chạy OCR thật trên bộ hồi quy 22 trang.
