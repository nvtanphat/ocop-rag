# Kiểm tra các tầng truy vấn OCOP — 28/10/2026

Đo trên corpus đang chạy, hybrid và rerank bật. Các thay đổi có sẵn trong cây làm việc được giữ làm baseline. Bộ phát triển giữ nguyên lock; bộ câu hỏi bổ sung và kết quả chi tiết nằm ngoài repo tại `%TEMP%/ocop-runtime-debug/`.

## 1. Router, hội thoại, catalog và bộ nhớ — đạt cổng chấp nhận

Bất biến: chỉ chọn công cụ đã đăng ký, tối đa năm lượt gọi; không đổi quyết định đã ghim theo năm; lời chào giữ chủ đề; đại từ chỉ dùng thực thể đã nhắc; tên và tập thực thể không bị mất khi chuẩn hóa hoặc đổi đối tượng.

| ID | Tầng hỏng | Triệu chứng và nguyên nhân đo được |
| --- | --- | --- |
| identity-accent | `catalog.link` | Nối `Thúy Hương` sang `Thụy Hương`; partial matching luôn bỏ dấu. Unicode dạng NFD cũng bị tách sai trước khi chuẩn hóa. |
| explicit-set | `extract_slots` | Cả ba cách nêu cặp sản phẩm qua API chỉ giữ một tên. Nhánh exact bỏ qua partial và bước chọn scalar loại các match còn lại. |
| name-boundary | `catalog.link` | Lượt API đầu sau sửa đạt 5/6 tập thực thể: `HANA, ST25 và RVT` chỉ giữ RVT. Đổi dấu phẩy thành `và` trong phép gọi thẳng nhận đủ ba; kiểm mở rộng tên đã bỏ qua ranh giới danh sách. |
| plural-count | `memory` | Ba sản phẩm đã nhắc chỉ lấy hai; mọi lượng từ dùng chung lát cắt `[:2]`. Khi chỉ có hai đối tượng, yêu cầu ba cũng không được phát hiện là thiếu. |
| referent-length | `memory.sanitize` | Tên 74 ký tự bị mất; slots cho phép 128 nhưng referent chỉ giữ 64. Catalog có một tên trong khoảng 65–128 ký tự. |
| code-case | `catalog.link` | Mã viết thường không nối tới mã viết hoa trong nhãn; hình dạng mã bị kiểm ở câu hỏi thay vì nhãn catalog. |

Sửa cơ chế:

- [catalog.py:214](../ai_core/orchestration/ocop/catalog.py#L214): NFC trước khi tách từ; cùng chính sách dấu với exact matching; hình dạng mã lấy từ nhãn, vẫn yêu cầu tên phân biệt duy nhất. [Ranh giới tên tại dòng 228](../ai_core/orchestration/ocop/catalog.py#L228) dùng loại ký tự, đồng thời giữ kiểm hậu tố mã có dấu nối.
- [router.py:329](../ai_core/orchestration/ocop/router.py#L329): hợp nhất exact/partial không chồng vị trí, khử trùng và giữ `product_names` theo thứ tự câu hỏi.
- [memory.py:126](../ai_core/orchestration/ocop/memory.py#L126), [language.py:40](../ai_core/orchestration/ocop/language.py#L40), [ocop_language.yaml:84](../configs/ocop_language.yaml#L84): lượng từ và đại từ lấy từ cấu hình; kiểm đủ số đối tượng; [giới hạn tên tại memory.py:54](../ai_core/orchestration/ocop/memory.py#L54) nhất quán với slots. Giữ giao diện ngữ pháp mà công cụ phân rã truy vấn đang dùng.

Tiền lệ đã đọc trước thiết kế: [TREC CAsT — multi-turn entity graphs](https://trec.nist.gov/pubs/trec30/papers/CMU-LTI-CAsT.pdf), [LlamaIndex — standalone question rewriting](https://developers.llamaindex.ai/python/examples/chat_engine/chat_engine_condense_question/), ADR-007 và ADR-009. Áp dụng việc giữ trạng thái thực thể riêng với bằng chứng; không thêm framework hay tên riêng vào mã runtime.

| Bộ đo | Trước | Sau |
| --- | --- | --- |
| Test mới, offline | 5/23 | 23/23 |
| API riêng: đúng tập sản phẩm | 0/6 | 6/6 |
| API riêng: đúng ý định | 5/6 | 6/6 |
| API riêng: có công cụ bắt buộc | 5/6 | 6/6 |
| API riêng: không truy xuất bổ sung | 0/6 | 0/6, chuyển sang kiểm planner |
| API 26 câu: ý định | 26/26 | 26/26 |
| API 26 câu: công cụ và trần riêng từng câu | 26/26 | 26/26 |
| API 26 câu: chấm đáp án | 24/26 | 25/26 |
| Phát triển khóa: `intent_ok` | 49/51 | 49/51 |
| Phát triển khóa: `tool_ok` | 50/51 | 50/51 |
| Phát triển khóa: `page_in_prompt` | 35/35 | 35/35 |
| Phát triển khóa: `top1_page_ok` | 28/35 | 28/35 |

Lượt phát triển trên bản sửa cuối giữ nguyên cả bốn chỉ số, không có lỗi chạy và `content_ok=35/35`. Độ trễ median/max trước là 17,40/150,97 giây, sau là 17,58/136,23 giây; chưa kết luận cải thiện tốc độ từ một lượt đối chiếu.

Chênh một câu ở lượt LLM thật được xem là biến thiên, không quy thành hiệu quả sửa router. C3 tiếp tục hỏi rõ văn bản chứa mẫu. Chuỗi hội thoại gốc năm lượt giữ đúng phạm vi ở 5/5 lượt, lần lượt trả các dữ kiện đã đối chiếu nguồn: HANA 4 sao, ST25 4 sao, điểm ST25 76,3, hợp tác xã Thụy Hương, giấy chứng nhận 36 tháng.

Không đồng nhất citation đúng với bằng chứng vào prompt. Hai chỉ số prompt ở trên lấy từ bộ đo dùng LLM stub; chất lượng trả lời được đo riêng qua API dùng LLM thật.

Hai chênh lệch intent hiện có của bộ khóa là ID 12 và 36: yêu cầu truy cập hồ sơ riêng bị từ chối bằng `OUT_OF_SCOPE`, trong khi gold chấp nhận `CLARIFY`/`DOSSIER_REVIEW`. Giữ nguyên gold và hành vi từ chối; không tính đây là lỗi trả lời câu hỏi tra cứu nội dung OCOP. Chênh lệch công cụ ID 35 được để riêng cho bước kiểm planner và an toàn khẳng định số sao.

Kiểm chứng:

- [test_router_entity_sets.py](../tests/ocop/orchestration/test_router_entity_sets.py): tắt riêng catalog có 8 ca thất bại; tắt tạo slots có 5 ca thất bại; tắt bộ nhớ có 6 ca thất bại. Chỉ tắt sửa ranh giới tên có 4 ca thất bại, hai ca mã dấu nối vẫn đạt. Khôi phục bản sửa: 23/23 đạt.
- Toàn bộ Python/OCR trên bản sửa cuối: 1.024 test đạt. Frontend build thành công, 13 test đạt. Lint các file sửa đạt.
- Roundtrip toàn bộ nhãn sản phẩm trong catalog qua slot extraction: 93/93 giữ đúng tên; đây là kiểm tính nhất quán, không phải chấm chất lượng câu trả lời.
- Fixture test độ sâu rerank trước đó chỉ tạo 20 ứng viên nhưng đòi ngân sách cấu hình 24. Đã sửa fixture tạo đủ ứng viên theo cấu hình; không đổi truy xuất hay gold.
- Dấu vân tay giữ `ocop-evidence-b531594eddc8`; `state=ready`, `lineage_ok=true`, `neo4j_ready=true`; số nút/cạnh yêu cầu giữ 12.619/22.429. Kiểm lại cả khi tắt và khôi phục từng cơ chế.

Lượt baseline API đầu gặp 503 do thêm trường cấu hình khi server còn dùng schema cũ. Các ca đó đã được chạy lại với cấu hình baseline; bộ baseline hợp lệ đủ 26 phản hồi HTTP 200.

Hai lần cold-start API cuối bị lỗi native `torch_cpu.dll` khi tải reranker. Phép thử riêng cho thấy tải embedding rồi reranker bằng mmap vẫn lỗi trên luồng chính; Safetensors 0.8.0/mmap cũng lỗi, còn cùng trọng số với `pread` tải thành công. Lượt API hợp lệ cuối chạy cùng profile hybrid, rerank 24 và cùng trọng số, qua script tạm dùng Safetensors 0.8.0/pread riêng trong `%TEMP%`; thư viện toàn máy chưa đổi. Đây là biện pháp phục hồi để đo, chưa phải sửa triển khai lâu dài. Dấu vết và cách sửa đọc mô hình sẽ được xử lý ở tầng truy xuất/cấu hình. Tham chiếu: [ComfyUI #15424](https://github.com/Comfy-Org/ComfyUI/issues/15424), [InvokeAI #9957](https://github.com/invoke-ai/InvokeAI/issues/9957).

Còn kiểm ở thành phần tiếp theo: truy xuất bổ sung cho câu recognition đơn giản; chọn đúng vai trò/cột trong câu trả lời; C1 thiếu một ý trong lượt baseline; C3 hỏi rõ văn bản chứa mẫu. Chưa thay chính sách câu trả lời cho các ca này.

## 2–10. Chưa duyệt

Tiếp tục theo đúng thứ tự từ thành phần 2. Chưa có kết luận đạt cho các thành phần này.
