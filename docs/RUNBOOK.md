# Sổ tay Vận hành Hệ thống OCOP GraphRAG (Operations Runbook)

Tài liệu cung cấp hướng dẫn thực thi các tác vụ vận hành thường ngày: xây dựng dữ liệu (build corpus), chạy chế độ kiểm thử mẫu debug (`allow_partial_debug`), đánh giá E2E, quản lý thẩm định hồ sơ, và xử lý các sự cố vận hành thường gặp.

---

## 1. Xây dựng Dữ liệu Toàn diện (Full Corpus Build)

Tác vụ đọc toàn bộ 12 văn bản PDF, thực hiện nhận dạng OCR các trang scan, trích xuất cấu trúc văn bản, sinh đồ thị tri thức và tạo chỉ mục tìm kiếm.

```powershell
# 1. Kiểm tra trạng thái hiện tại của dữ liệu
python tools/cli.py status

# 2. Xây dựng toàn bộ các tầng dữ liệu (không khởi động server)
python tools/cli.py run --build-only --dpi 300

# 3. (Tùy chọn) Xây dựng kèm chỉ mục Dense Vector (yêu cầu Qdrant)
python tools/cli.py run --build-only --dense --dpi 300

# 4. (Tùy chọn) Tái tạo lại toàn bộ từ đầu (xóa cache trung gian cũ)
python tools/cli.py run --build-only --refresh --dpi 300
```

---

## 2. Vận hành Chế độ Mẫu Debug (Partial Corpus & `allow_partial_debug`)

### Khái niệm
Để phục vụ việc kiểm thử nhanh các tính năng mà không phải chờ xử lý toàn bộ 583 trang PDF, hệ thống cho phép trích xuất một tập mẫu giới hạn các trang đại diện (ví dụ trong `ocop-work-sample`). Khi đó, trạng thái dữ liệu trong manifest được đánh dấu là `partial_debug_not_production`.

### Cơ chế An toàn HTTP 409
Theo thiết kế an toàn sản xuất (AGENTS.md, ADR-001), dịch vụ API chính thức (`backend/api/ocop_routes.py`) **từ chối phục vụ (HTTP 409 Conflict)** đối với tập dữ liệu mang nhãn `partial_debug_not_production`. Điều này nhằm ngăn chặn tuyệt đối việc vô tình đưa dữ liệu thử nghiệm chưa hoàn chỉnh lên môi trường sản xuất.

### Cách Chạy Debug trên Tập Mẫu
Để chạy thử nghiệm trên tập dữ liệu mẫu, người vận hành có hai phương thức:

1. **Khởi tạo ứng dụng Debug riêng biệt (`backend/api/ocop_debug.py`)**:
   Sử dụng hàm `create_debug_app(root, allow_partial_debug=True)` để khởi tạo FastAPI app chuyên biệt cho debug.
   ```python
   from pathlib import Path
   import uvicorn
   from backend.api.ocop_debug import create_debug_app

   app = create_debug_app(Path("D:/AgentAI/OCOP-RAG/ocop-work-sample"), allow_partial_debug=True)
   uvicorn.run(app, host="127.0.0.1", port=8001)
   ```

2. **Khởi tạo Agent trực tiếp qua Python**:
   ```python
   from pathlib import Path
   from ai_core.orchestration.ocop.workflow import OcopAgent

   corpus_dir = Path("D:/AgentAI/OCOP-RAG/ocop-work-sample")
   agent = OcopAgent(corpus_dir, allow_partial_debug=True)
   response = agent.ask("Tiêu chí 1.1 yêu cầu điểm số như thế nào?")
   print(response.model_dump_json(indent=2))
   ```

3. **Chạy lại chỉ mục trên tập mẫu**:
   ```powershell
   Set-Location D:\AgentAI\OCOP-RAG\ocop-work-sample
   python build_sample.py --reindex
   ```

---

## 3. Chạy Kiểm thử Toàn trình (E2E Run)

Bộ kiểm thử E2E gồm 12 câu hỏi tiêu chuẩn đo lường khả năng phân luồng ý định (`intent`), bộ công cụ được kích hoạt (`tools_used`) và tính toàn vẹn của trích dẫn (`citations`):

```powershell
Set-Location D:\AgentAI\OCOP-RAG\ocop-work-sample
python run_e2e.py
```
* **Chế độ kiểm tra nhanh (không dùng LLM)**: Đánh giá phân luồng và trích xuất bằng chứng thuần túy chỉ trong khoảng 5 giây.
* **Tiêu chuẩn đạt**: 100% 12 câu hỏi đều vượt qua các điều kiện kiểm tra (`checks: passed`).

---

## 4. Quản lý Thẩm định Người dùng (Human Review CLI)

Hệ thống tích hợp công cụ dòng lệnh để quản lý các mục dữ liệu cần con người duyệt:

```powershell
# 1. Xem thống kê hàng đợi thẩm định
python tools/cli.py review stats

# 2. Xuất hàng đợi ra file JSONL kèm crop hình ảnh đối soát
python tools/cli.py review queue --out data/review/ocop_review_queue.jsonl --render

# 3. Ghi nhận quyết định phê duyệt (Approve)
python tools/cli.py review decide --target-id "ocop:evidence:..." --content-hash "<sha256>" --decision approve --reviewer "chuyengia_01" --notes "Đã đối chiếu trang 3"

# 4. Ghi nhận quyết định bác bỏ (Reject)
python tools/cli.py review decide --target-id "ocop:evidence:..." --content-hash "<sha256>" --decision reject --reviewer "chuyengia_01" --notes "Bảng OCR sai số liệu"
```

---

## 5. Xử lý Sự cố Thường gặp (Troubleshooting)

### Sự cố 1: API trả về lỗi HTTP 409 "Corpus snapshot is not ready for production"
* **Nguyên nhân**: Thư mục dữ liệu đang ở chế độ mẫu debug (`partial_debug_not_production`) hoặc chưa hoàn tất bước build đồ thị.
* **Khắc phục**:
  * Nếu trên môi trường sản xuất: Chạy lại lệnh build đầy đủ `python tools/cli.py run --build-only`.
  * Nếu đang phát triển cục bộ: Sử dụng `backend/api/ocop_debug.py` với cờ `allow_partial_debug=True`.

### Sự cố 2: Lỗi thiếu mô hình khi chạy hoàn toàn Offline (`HF_HUB_OFFLINE=1`)
* **Nguyên nhân**: Chưa tải sẵn trọng số `google/embeddinggemma-300m` hoặc `BAAI/bge-reranker-v2-m3` về máy cục bộ.
* **Khắc phục**:
  1. Tải trọng số mô hình về thư mục cục bộ (ví dụ: `D:/AgentAI/OCOP-RAG/models/bge-reranker-v2-m3`).
  2. Khai báo biến môi trường `OCOP_MODELS_DIR=D:/AgentAI/OCOP-RAG/models` trong `.env`. Hệ thống sẽ tự động tìm kiếm và nạp mô hình cục bộ qua hàm `resolve_local_model_path`.

### Sự cố 3: Lỗi mã hóa ký tự trên Windows (`UnicodeEncodeError: 'charmap' codec...`)
* **Nguyên nhân**: Màn hình dòng lệnh Windows PowerShell mặc định sử dụng bảng mã `cp1252` thay vì `UTF-8`.
* **Khắc phục**:
  * Các CLI của hệ thống (`tools/cli.py`, `tools/debug_cli.py`) đã tích hợp sẵn cơ chế cấu hình tự động UTF-8 (`sys.stdout.reconfigure(encoding='utf-8', errors='replace')`).
  * Nếu chạy script tùy biến khác, hãy đặt biến môi trường:
    ```powershell
    $env:PYTHONIOENCODING="utf-8"
    ```

### Sự cố 4: Lỗi khóa ghi tiến trình (`RuntimeError: Another OCOP build may be active`)
* **Nguyên nhân**: Một tiến trình build trước đó bị ngắt đột ngột khiến tệp khóa độc quyền chưa được giải phóng.
* **Khắc phục**: Kiểm tra xem còn tiến trình python nào đang build dở dang hay không. Nếu không, xóa tệp khóa tại `data/processed/ocop/.build.lock`.
