# ADR 007: Từ vựng trong tệp cấu hình và danh mục thực thể sinh từ nguồn

## Bối cảnh
Router cũ chứa danh sách tỉnh, danh sách sản phẩm, hàng chục tuple từ khóa và so khớp chuỗi đã bỏ dấu. Hệ quả đã đo: "đánh giá lại" thành địa danh "Gia Lai", "trả khóa API" thành sản phẩm "trà", slot sản phẩm dính cụm nghi vấn, đại từ "nó" làm đứt hội thoại, câu "1.6" bị coi ngoài phạm vi. Thêm một văn bản hoặc một sản phẩm mới đòi sửa mã.

## Quyết định
1. **Từ vựng ngôn ngữ** nằm một nơi: `configs/ocop_language.yaml`, có schema pydantic (`extra=forbid`) và test kiểm schema. Gồm từ dừng, từ khóa ý định, từ mở đầu hội thoại, đại từ, ký hiệu loại văn bản, danh từ cấu trúc (Điều, Mẫu, Phiếu, Trang), thang hạng sao, tên đơn vị hành chính cấp tỉnh.
2. **Danh mục thực thể** (`ai_core/orchestration/ocop/catalog.py`) sinh lúc dựng chỉ mục từ `configs/ocop_sources.json` và graph đã kiểm: văn bản (số hiệu, loại, năm), địa danh, sản phẩm, nhóm sản phẩm, chủ thể, cơ quan, phiếu, mẫu. Lưu cạnh chỉ mục, mã băm ghi trong manifest; sai mã băm thì danh mục bị bỏ.
3. **Chính sách dấu**: câu có dấu thì thực thể và cụm từ khóa phải khớp **có dấu** (đoạn đã gõ dấu phải bằng cụm cấu hình); câu không dấu mới khớp trên chuỗi đã gập dấu. Điều này loại các va chạm "diện/điền", "quan/quận", "giá lại/Gia Lai".
4. **Chính sách tuyến**: riêng tư → DOSSIER (cần AuthContext tin cậy); nối tiếp (từ mở đầu hoặc đại từ cộng phiên) → FOLLOWUP kế thừa slot; mảnh quá ngắn hoặc mã tiêu chí trơ trụi → CLARIFY nêu thiếu gì; không có tín hiệu miền → OUT_OF_SCOPE. LLM chỉ được gợi ý ý định thuộc enum và không bao giờ cấp công cụ hay quyền.
5. **Công cụ chính và phụ**: công cụ phụ làm giàu câu trả lời nhưng thiếu dữ liệu thì chỉ ghi chú, không chặn công cụ chính (PLN-01).
6. Số hiệu văn bản được giải qua đoạn số của số hiệu trong registry ("148" không khớp "1489"); văn bản được nhận theo loại và năm qua danh mục ("Luật ... 2023").

## Dự án đã tham khảo
| Dự án / tài liệu | Ngày đọc | Ý tưởng | Quyết định |
| --- | --- | --- | --- |
| Aurelio `semantic-router` (giấy phép ghi MIT theo trang tổng hợp, chưa xác minh tại kho) | 2026-10-22 | Tuyến định nghĩa bằng câu mẫu, ngưỡng điểm chỉnh theo dữ liệu có nhãn | Không thêm thư viện: cần embedding mỗi câu hỏi và ngưỡng chưa đo; giữ cue có kiểm soát, lấy ý tưởng "ngưỡng chỉnh bằng bộ đo" |
| LangGraph adaptive/corrective RAG (cookbook Mistral, Elastic) | 2026-10-22 | Phân tích câu hỏi → chọn nguồn; chấm tài liệu rồi sửa | Đã có luồng LangGraph route→plan→execute→grade→recover; giữ, chỉ thêm phân tích có cấu trúc và chấm sau ghép |
| LlamaIndex `RouterQueryEngine` | 2026-10-22 | Bộ chọn trả enum hợp lệ; lựa chọn nhiều công cụ | Áp dụng nguyên tắc: đầu ra LLM chỉ là gợi ý trong enum |
| DSPy | 2026-10-22 | Tối ưu prompt/định tuyến bằng số đo | Chưa áp dụng; bộ đo của dự án đóng vai trò đó, ghi nhận làm hướng tiếp theo |
| pyvi, underthesea (tách từ) | 2026-10-22 | Tách từ tiếng Việt | Không dùng cho định tuyến: cue theo cụm từ nguyên vẹn đủ và tránh thêm mô hình |

## Hệ quả
* Thêm văn bản hoặc sản phẩm mới: dựng lại chỉ mục là đủ, không sửa mã (xem docs/DEVELOPMENT.md).
* Test `tests/ocop/test_no_corpus_literals.py` chặn literal của corpus quay lại mã runtime.
