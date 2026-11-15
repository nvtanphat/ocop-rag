# ADR 006: Cửa sổ trích đoạn theo câu hỏi và chuỗi cha ngắn từ graph

## Bối cảnh
Văn bản được đánh chỉ mục của mỗi chunk gồm tiền tố cấu trúc lấy từ graph rồi tới đoạn gốc. Nếu tiền tố chứa cả nhãn các điểm/khoản lân cận, chunk phình nhiều lần so với đoạn gốc; nếu phần trích đưa vào prompt luôn lấy phần đầu chunk, nội dung ở cuối đoạn (ví dụ danh sách thành viên một hội đồng) bị cắt khỏi prompt. Ngân sách token và bộ chấm đủ/thiếu phải tính trên đúng văn bản gửi cho LLM.

## Quyết định
1. **Chuỗi cha ngắn** (`ai_core/retrieval/ocop/graph_context.py`): chỉ các tổ tiên trực tiếp của nút sâu nhất mà chunk chứa, khử trùng với nội dung chunk, mỗi nhãn cắt ở ranh giới từ, tổng giới hạn theo tokenizer (khi có) hoặc ước lượng; lưu riêng ở `context.parent_chain`.
2. **Trích đoạn từ `raw_text`** (`ai_core/orchestration/ocop/context.py`): chấm độ phủ trên cửa sổ thực sự vừa ngân sách; câu quá dài được cắt theo vị trí từ, có dấu "…"; nhãn cột bảng đi kèm dòng bảng.
3. **Ngân sách trên toàn prompt** (`configs/ocop_retrieval.yaml`): system + câu hỏi + các khối SOURCE + phần dành cho đầu ra; thu hẹp cửa sổ dài nhất trước, bỏ hàng xếp thấp nhất sau cùng.
4. **Kiểm độ phủ sau khi ghép**: tỉ lệ thuật ngữ câu hỏi có trong đúng văn bản gửi LLM; thấp hơn ngưỡng thì không sinh, trả bản trích xuất.
5. Văn bản gửi bộ kiểm claim là cửa sổ mô hình nhìn thấy (không gồm dấu "…" và ứng viên OCR).

## Hệ quả
* Chunk không phình bởi nhãn lặp; dense và BM25 nhìn cùng một ngữ cảnh ngắn.
* Câu hỏi được chấm đủ/thiếu trên đúng nội dung gửi LLM.
* Đổi định dạng chunk buộc dựng lại chỉ mục (`INDEX_VERSION` đổi theo mã nguồn).
