# ADR 007: Từ vựng trong tệp cấu hình và danh mục thực thể sinh từ nguồn

## Bối cảnh
Danh sách tỉnh, sản phẩm và từ khóa viết trong mã router, kèm so khớp chuỗi đã bỏ dấu, dẫn tới nhận nhầm thực thể ("đánh giá lại" thành địa danh, "trả khóa API" thành sản phẩm "trà"), đứt hội thoại ở đại từ và phải sửa mã mỗi khi thêm văn bản hoặc sản phẩm.

## Quyết định
1. **Từ vựng ngôn ngữ** nằm một nơi: `configs/ocop_language.yaml`, có schema pydantic (`extra=forbid`) và test kiểm schema. Gồm từ dừng, từ khóa ý định, từ mở đầu hội thoại, đại từ, ký hiệu loại văn bản, danh từ cấu trúc (Điều, Mẫu, Phiếu, Trang), thang hạng sao, tên đơn vị hành chính cấp tỉnh.
2. **Danh mục thực thể** (`ai_core/orchestration/ocop/catalog.py`) sinh lúc dựng chỉ mục từ `configs/ocop_sources.json` và graph đã kiểm: văn bản (số hiệu, loại, năm), địa danh, sản phẩm, nhóm sản phẩm, chủ thể, cơ quan, phiếu, mẫu. Lưu cạnh chỉ mục, mã băm ghi trong manifest; sai mã băm thì danh mục bị bỏ.
3. **Chính sách dấu**: câu có dấu thì thực thể và cụm từ khóa phải khớp có dấu; câu không dấu mới khớp trên chuỗi đã gập dấu. Cách này tránh va chạm kiểu "diện/điền", "quan/quận", "giá lại/Gia Lai".
4. **Chính sách tuyến**: riêng tư → DOSSIER (cần AuthContext tin cậy); nối tiếp (từ mở đầu hoặc đại từ cộng phiên) → FOLLOWUP kế thừa slot; mảnh quá ngắn hoặc mã tiêu chí trơ trụi → CLARIFY nêu thiếu gì; không có tín hiệu miền → OUT_OF_SCOPE. LLM chỉ gợi ý ý định thuộc enum, không bao giờ cấp công cụ hay quyền.
5. **Công cụ chính và phụ**: công cụ phụ làm giàu câu trả lời; thiếu dữ liệu thì chỉ ghi chú, không chặn công cụ chính.
6. Số hiệu văn bản được giải qua đoạn số trong registry ("148" không khớp "1489"); văn bản được nhận theo loại và năm qua danh mục.

## Hệ quả
* Thêm văn bản hoặc sản phẩm mới chỉ cần dựng lại chỉ mục, không sửa mã (xem [DEVELOPMENT](../DEVELOPMENT.md)).
* `tests/ocop/contracts/test_no_corpus_literals.py` chặn literal theo corpus xuất hiện trong mã runtime.
