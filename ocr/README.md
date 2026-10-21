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

CLI dataset độc lập (từ repo sau khi cài editable, hoặc từ thư mục `ocr`):

```powershell
python -m ocop_ocr run --help
python -m ocop_ocr run --dataset D:/AgentAI/OCOP-RAG/ocr-dataset-pilot --workers 3 --page VN.OCOP.QD26.2026:18
python -m ocop_ocr export --dataset D:/AgentAI/OCOP-RAG/ocr-dataset-pilot
python -m ocop_ocr import --dataset D:/AgentAI/OCOP-RAG/ocr-dataset-pilot
python -m ocop_ocr status --dataset D:/AgentAI/OCOP-RAG/ocr-dataset-pilot
```

`--page` tạo dataset một phần (`complete=false`), không được đưa vào RAG
production. `run` dùng 3 tiến trình mặc định; hàm Python cũ giữ mặc định tuần tự.
Mỗi worker nạp model cục bộ qua cache trong tiến trình và dùng 2 luồng Torch.
CLI dataset không áp tự sửa dấu tiếng Việt; chỉ Markdown import thay đổi chữ.

Sửa cột Chữ hoặc ô bảng trong `review/<source_id>/p###.md`, giữ nguyên ID khối,
số hàng/cột và front matter nguồn. Đổi `trang_thai` thành `da_duyet` sau khi
đối chiếu ảnh. Các ký tự `|`, xuống dòng dùng HTML entity để giữ cấu trúc bảng.
Ô trống có marker `<!-- blank -->`; thay marker bằng chữ khi cần sửa.
Export tạo ảnh 150 DPI từ PDF đã kiểm SHA và không ghi đè file Markdown có sẵn.
File lỗi được báo `file:dòng`; không ghi bất kỳ correction nào trước khi tất cả
file hợp lệ. Nhập lại không sửa là no-op. Hash gốc lệch bị từ chối.

Dataset giữ `ocr_text`, bbox, SHA và trạng thái chữ được duyệt, không xác minh
thực thể/quan hệ hay giá trị điểm/sao. `review/corrections.jsonl` chỉ append.
Nếu import bị ngắt, reader từ chối dataset có `.pending-import.json`; chạy lại
`import` phục hồi giao dịch và không nhân đôi correction.
Khóa dùng khóa hệ điều hành kèm PID; tiến trình chết tự nhả khóa, file khóa
còn lại để chẩn đoán, không cần xóa thủ công.
Lệnh `status` cũng đọc được `run-state.json` khi chưa có dataset công bố:
trạng thái chạy bị bỏ dở được báo `interrupted`, lỗi worker báo `failed`.
Chạy lại đúng lệnh `run` để dùng cache trang đã xong và thử lại trang còn thiếu.

Đầu ra raw của parser chưa phải dataset được duyệt. Lớp chuyển tiếp tại
`ai_core/processing/ocop` dành cho script cũ; mã nguồn OCR chỉ nằm ở đây.

RAG đọc dataset hoàn chỉnh bằng:

```powershell
python tools/cli.py run --ocr-dataset D:/AgentAI/OCOP-RAG/ocr-dataset --build-only
```

Lệnh này từ chối dataset thiếu trang, SHA lệch, digest sai hoặc schema chưa hỗ
trợ; không gọi OCR. `smoke` nhận `--ocr-dataset` và cho phép chọn trang thí điểm
từ dataset một phần. Không dùng lệnh full trước khi cổng thí điểm được xác nhận.

Kiểm chứng việc tách: 22 trang chạy native (OCR tắt) giống hệt PageArtifact
trước tách; đây không thay thế kiểm chứng chạy OCR thật trên bộ hồi quy 22 trang.

Trên máy ít RAM, ba worker dùng chung khóa hệ điều hành cho hai bước có đỉnh
bộ nhớ lớn: phát hiện chữ CRAFT và dự đoán layout Paddle. Nhận dạng và xử lý
trang vẫn chạy trong ba worker; DPI, canvas và ngưỡng nhận dạng giữ nguyên.
Khóa mặc định nằm ở thư mục tạm (`ocop-ocr-peak.lock`); tiến trình bị dừng
cứng tự nhả khóa. Có thể đặt `OCOP_OCR_PEAK_LOCK` để các lệnh OCR trên cùng
máy dùng chung một đường dẫn khóa. Không xóa file khóa khi còn worker chạy.
