# ADR 004: Tích hợp mô hình ngôn ngữ (LLM) qua giao thức API chuẩn

## Bối cảnh
Việc gắn chặt mã nguồn với một thư viện nội bộ hoặc nhúng thẳng trọng số LLM vào tiến trình ứng dụng gây lãng phí tài nguyên RAM/VRAM, khó scale độc lập và không linh hoạt khi chuyển đổi giữa môi trường phát triển cục bộ và môi trường máy chủ đám mây.

## Quyết định
* Tách biệt hoàn toàn tầng điều phối LLM thông qua giao diện API đồng nhất (`ai_core/orchestration/ocop/llm.py`):
  * **Cục bộ (mặc định)**: Kết nối tới Ollama API (`http://127.0.0.1:11434`) với mô hình `qwen3.5:2b`.
  * **API tương thích OpenAI**: Cho phép cấu hình qua `OCOP_ANSWER_OPENAI_BASE_URL` và `OCOP_EXTRACT_OPENAI_BASE_URL`.
* Cơ chế fall-closed: Khi LLM không sẵn sàng hoặc gặp lỗi kết nối, hệ thống tự động suy thoái mềm (graceful degradation) về chế độ trích xuất bằng chứng thuần túy (`retrieval_only` / `--no-llm`).

## Hệ quả
* Ứng dụng nhẹ, dễ đóng gói container và chạy thử nghiệm.
* Tách bạch chi phí tính toán giữa việc chuẩn bị chỉ mục (chủ yếu là CPU/GPU cho embedding/OCR) và việc sinh câu trả lời.
