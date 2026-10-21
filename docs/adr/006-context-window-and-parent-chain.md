# ADR 006: Cửa sổ trích đoạn theo câu hỏi và chuỗi cha ngắn từ graph

## Bối cảnh
Văn bản được đánh chỉ mục của mỗi chunk gồm tiền tố cấu trúc lấy từ graph rồi mới tới đoạn gốc. Trước đây tiền tố gồm cả nhãn các điểm/khoản lân cận (đoạn gốc 720 ký tự thành 3232 ký tự) và phần trích đưa vào prompt LLM lấy 1250 ký tự **đầu** chunk, nên đoạn gốc (ví dụ danh sách bộ trong thành phần Hội đồng trung ương) bị cắt khỏi prompt. Ngân sách token chỉ tính cho phần trích, bộ chấm đủ/thiếu chạy trước khi ghép nên không thấy phần bị cắt.

## Quyết định
1. **Chuỗi cha ngắn** (`ai_core/retrieval/ocop/graph_context.py`): chỉ các tổ tiên trực tiếp của nút sâu nhất mà chunk chứa, đã khử trùng với nội dung chunk, mỗi nhãn cắt ở ranh giới từ, tổng giới hạn theo tokenizer (khi có) hoặc ước lượng; lưu riêng ở `context.parent_chain`.
2. **Trích đoạn từ `raw_text`** (`ai_core/orchestration/ocop/context.py`): chọn cửa sổ gồm các dòng/câu nguyên vẹn bao nhiều thuật ngữ khác nhau của câu hỏi nhất, cắt có đánh dấu "…", nhãn cột bảng đi kèm dòng bảng.
3. **Ngân sách trên toàn prompt** (`configs/ocop_retrieval.yaml`): system + câu hỏi + các khối SOURCE + phần dành cho đầu ra; thu hẹp cửa sổ dài nhất trước, bỏ hàng xếp thấp nhất sau cùng.
4. **Bộ kiểm độ phủ sau ghép**: tỉ lệ thuật ngữ câu hỏi có mặt trong đúng văn bản đã gửi LLM; thấp hơn ngưỡng thì không sinh, trả trích xuất.
5. Văn bản gửi bộ kiểm claim chính là cửa sổ mô hình nhìn thấy (không gồm dấu "…" và ứng viên OCR).

## Dự án đã tham khảo
| Dự án / tài liệu | Ngày đọc | Ý tưởng | Quyết định |
| --- | --- | --- | --- |
| Anthropic, *Introducing Contextual Retrieval* (2024-09) | 2026-10-22 | Một câu ngữ cảnh ngắn (50–100 token) đặt trước chunk cho cả BM25 lẫn embedding; giảm 35% → 49% → 67% lỗi top-20 khi kết hợp BM25 và reranker | Áp dụng ý tưởng, nhưng ngữ cảnh lấy tất định từ graph đã kiểm (không sinh bằng LLM) để không thêm nội dung chưa kiểm vào chỉ mục |
| LlamaIndex `HierarchicalNodeParser` + `AutoMergingRetriever`, `SentenceWindowNodeParser` | 2026-10-22 | Truy xuất đoạn nhỏ, hiển thị cửa sổ/cha lớn hơn; nhãn cha tách khỏi văn bản hiển thị | Áp dụng nguyên tắc tách "văn bản truy xuất" và "văn bản hiển thị"; không thêm thư viện |
| RAGFlow DeepDoc (Apache-2.0) | 2026-10-22 | Chunk theo cấu trúc tài liệu, bảng giữ ngữ cảnh tiêu đề cột | Áp dụng nhãn cột trong trích đoạn bảng; chunker cấu trúc đã có sẵn nên giữ |
| Arxiv 2504.19754 (Reconstructing Context: chunking strategies for RAG) | 2026-10-22 | Chunk theo ngữ nghĩa/cấu trúc và ngữ cảnh muộn đều có đánh đổi chi phí | Ghi nhận; giữ chunker cấu trúc tất định |

Không lấy mã nguồn từ các dự án trên.

## Hệ quả
* Chunk không còn phình bởi nhãn lặp; dense và BM25 nhìn cùng một ngữ cảnh ngắn.
* Danh sách nằm sau tiền tố không còn bị cắt khỏi prompt; câu hỏi được chấm đủ/thiếu trên đúng nội dung gửi LLM.
* Đổi định dạng chunk buộc dựng lại chỉ mục (`INDEX_VERSION` đổi theo mã nguồn).
