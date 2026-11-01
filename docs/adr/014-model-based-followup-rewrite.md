# ADR 014: Viết lại câu hỏi nối tiếp có từ trỏ ngược bằng mô hình ngôn ngữ

Trạng thái: **Accepted**. Cài đặt: `ai_core/orchestration/ocop/followup_model.py`, `ai_core/orchestration/ocop/memory.py`, `ai_core/orchestration/ocop/workflow.py`.

## Bối cảnh

Trong hội thoại nhiều lượt, người dùng thường đặt các câu hỏi nối tiếp có đại từ hoặc cụm chỉ định trỏ ngược về quá khứ ("hãng đó", "siro lúc nãy", "nhóm đó", "cả hai").

Bộ viết lại theo quy tắc thuần túy (`ai_core/orchestration/ocop/memory.py:rewrite`) chỉ duy trì phạm vi của thực thể được nhắc gần nhất. Cách tiếp cận này bộc lộ các hạn chế:
1. Quy tắc không phân biệt được "hãng đó" là muốn hỏi về chủ thể (công ty) hay sản phẩm.
2. Từ "lúc nãy" có thể trỏ về câu hỏi cách đó 2 lượt chứ không phải lượt liền kề.
3. Cụm "nhóm đó" không suy luận được nhóm sản phẩm cụ thể nếu tên nhóm không xuất hiện ngay ở lượt trước.

Các dự án tham khảo ViCAS-RAG và Legal-RAG giải quyết vấn đề này bằng cách dùng một mô hình ngôn ngữ nhỏ viết lại câu hỏi nối tiếp thành câu hỏi độc lập (standalone question), nhưng kiểm soát chặt chẽ đầu ra bằng các ràng buộc từ vựng nghiêm ngặt nhằm chống ảo giác (hallucination).

## Quyết định

1. **Lưu lịch sử câu hỏi độc lập gần nhất trong bộ nhớ phiên**:
   - Mở rộng cấu trúc trạng thái phiên tại `ai_core/orchestration/ocop/memory.py` với trường `recent`: lưu tối đa 3 câu hỏi độc lập gần nhất (`MAX_TURNS = 3`), câu mới nhất đứng đầu.
   - Khi sanitize phiên, chỉ các chuỗi hợp lệ dưới 600 ký tự mới được giữ lại trong `recent`.

2. **Tầng mô hình viết lại câu hỏi nối tiếp (`ai_core/orchestration/ocop/followup_model.py`)**:
   - Điều kiện kích hoạt: khi có mô hình (`llm` khả dụng), phiên có lịch sử câu hỏi (`recent` không rỗng), và câu hỏi hiện tại chứa đại từ hoặc cụm chỉ định (`refers_back(question)` khớp từ vựng cấu hình `lang.followup.pronouns` hoặc `lang.followup.demonstrative`).
   - Gọi hàm `propose` truyền lịch sử theo thứ tự thời gian cũ trước mới sau (`recent[::-1]`) cùng câu hỏi hiện tại với prompt hệ thống yêu cầu chỉ trả về JSON `{"standalone": "..."}`.
   - Áp dụng kiểm tra kiểm thực tất định nghiêm ngặt qua hàm `validate`:
     - Độ dài chuỗi từ 8 đến 300 ký tự, không được trùng nguyên văn với câu hỏi ban đầu.
     - **Không sáng tạo số**: Mọi số xuất hiện trong câu viết lại phải là tập con (`issubset`) của các số có mặt trong câu hỏi hiện tại hoặc lịch sử hội thoại.
     - **Không sáng tạo tên riêng**: Mọi từ viết hoa (từ thứ hai trở đi trong câu) phải thuộc tập các từ đã biết trong ngữ cảnh hội thoại.
     - **Giới hạn từ mới**: Số lượng từ nội dung mới (từ thường dùng để nối câu như "thuộc", "của") không được vượt quá 2 từ (`len(words - allowed) <= 2`).
     - **Giữ lại ý hỏi**: Câu viết lại phải giữ lại ít nhất một phần từ nội dung cốt lõi của câu hỏi gốc (`not own.isdisjoint(words)`).
   - Văn bản viết lại chỉ dùng làm chuỗi tìm kiếm văn bản (`effective_query`), không dùng làm bằng chứng pháp lý; các slot cấu trúc phục vụ công cụ tra cứu bảng vẫn do luật quản lý.

3. **Bảo tồn câu hỏi người dùng khi thực thể mới không có trong câu trước (commit `5e200b2`)**:
   - Trong `memory.py:rewrite`, nếu người dùng hỏi về một sản phẩm hoặc chủ thể mới mà tên cũ không xuất hiện trong văn bản câu trước để hoán đổi (ví dụ: "Còn hạt sen của HTX Sen Huế được mấy sao?" sau câu hỏi "Siro của Hichagol..."), hệ thống nhận diện `unplaced` và chuyển sang phương pháp `state_scope`: giữ nguyên câu hỏi của người dùng kèm phạm vi bổ sung, thay vì viết lại nhầm thành sản phẩm cũ.

## Hệ quả

Đo lường ngày 2026-11-01 trên bộ dữ liệu `data/evaluations/ocop/ocop_session_memory_gold_50.json` (50 lượt hội thoại):
- Commit `6630d15`: số lượt tìm đúng trang vàng (`gold page found`) tăng từ 41/50 lên 44/50.
- Commit `5e200b2`: các ca SM013 và SM014 khôi phục đúng tên sản phẩm thay vì bị kéo theo sản phẩm cũ; tỷ lệ tìm đúng trang duy trì ổn định 44/50.
- Commit `909470f`: bổ sung nhận diện viết tắt tên chủ thể ("HTX" và "Hợp tác xã") trong `tools.py` giúp 4 hội thoại bị ảnh hưởng tăng từ 14/20 lên 16/20 trang vàng (SM013, SM015).

## Phương án đã cân nhắc

- **Cho phép mô hình viết lại tự do không ràng buộc từ vựng**:
  - Một câu viết lại có thể chứa năm, hạng sao hay tên chủ thể mà hội thoại chưa nhắc; câu như vậy làm lệch truy xuất. Chưa đo tần suất trên bộ vàng, nhưng Legal-RAG và ViCAS-RAG đều chặn đúng loại lỗi này (cấm thêm thông tin, bác bỏ số điều luật bịa ra), nên `validate` chặn số và tên riêng mới trước khi dùng câu viết lại.
- **Chỉ sử dụng quy tắc hoán đổi chuỗi**:
  - Tiết kiệm thời gian gọi LLM nhưng không thể xử lý các câu trỏ ngược phức tạp ("nó của đơn vị nào?", "quay lại sản phẩm lúc nãy"), dẫn đến việc từ chối trả lời hoặc tìm nhầm văn bản.
