# ADR 003: Không bật trust_remote_code và chọn BAAI/bge-reranker-v2-m3

## Bối cảnh
Một số mô hình reranker (ví dụ `Alibaba-NLP/gte-multilingual-reranker-base`) yêu cầu tham số `trust_remote_code=True` khi khởi tạo từ Hugging Face Transformers. Việc cho phép thực thi mã tùy ý từ bên ngoài tiềm ẩn rủi ro an ninh mạng, đồng thời gây lỗi nạp mô hình trên một số môi trường cô lập không có kết nối Internet (offline air-gapped).

## Quyết định
* Tuyệt đối không bật cờ `trust_remote_code=True` trong bất kỳ thành phần nào của hệ thống.
* Chuẩn hóa mô hình reranker mặc định sang `BAAI/bge-reranker-v2-m3` với revision được ghim cứng (`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`).
* Bổ sung cơ chế `resolve_local_model_path` tại `models_config.py` để ưu tiên nạp trọng số đã tải về từ thư mục cục bộ (`OCOP_MODELS_DIR`).

## Hệ quả
* Bảo đảm an toàn thực thi mã nguồn nội bộ.
* Hệ thống vận hành trơn tru ở chế độ hoàn toàn offline khi đã tải trọng số về đĩa.
