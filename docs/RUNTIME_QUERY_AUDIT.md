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

## 2. Planner và workflow — đạt cổng chấp nhận

Bất biến: chỉ thực thi tên trong registry; năm lượt tính theo số lần gọi thực tế; trạng thái chặn không được che bằng tìm kiếm chung; optional không làm thiếu công cụ bắt buộc; chỉ bỏ truy xuất bổ sung khi toàn bộ câu hỏi thuộc khung lookup đã biết và đủ tập thực thể đúng phạm vi nguồn.

| ID | Tầng hỏng | Triệu chứng và nguyên nhân đo được |
| --- | --- | --- |
| pair_partial | Evidence grader / workflow | Lookup trả 14 đoạn gắn đúng hai RecognitionRecord. Các ô tên chỉ đạt overlap 0,125, thấp hơn ngưỡng 0,13; ô chủ thể đạt 0. Grader trước sửa kết luận không có bằng chứng, optional search luôn chạy. |
| blocked-primary | Workflow | `entity_not_found` ở công cụ chính vẫn cho công cụ optional chạy, dù không được phép recovery từ trạng thái này. |
| optional-gap | Evidence grader | Optional structured tool không có kết quả bị cộng vào `missing_tools`, làm hạ mức bao phủ của công cụ bắt buộc đã hoàn tất. |
| call-budget | Planner | Bộ nhớ và mục bỏ qua bị tính như lần dispatch, chặn nhầm lượt gọi thứ năm. |
| targeted-budget | Workflow recovery | Bốn lượt chính cộng hai lần `search_part` tạo sáu lần tìm, nhưng recovery chỉ ghi một mục kết quả. Test tái hiện trước sửa thất bại với hai lần tìm thay vì một. |

Sửa cơ chế:

- [capabilities.py](../ai_core/orchestration/ocop/capabilities.py) khai báo loại bản ghi và slots định danh của adapter; [query_frames.py:19](../ai_core/orchestration/ocop/query_frames.py#L19) kiểm toàn bộ từ nội dung theo [khung ngôn ngữ cấu hình:100](../configs/ocop_language.yaml#L100), không đoán loại câu theo tên sản phẩm. Tác vụ không được giải thích hết, có vị từ mới hoặc câu hỏi nguyên nhân vẫn giữ tìm kiếm bổ sung.
- [evidence_grader.py:143](../ai_core/orchestration/ocop/evidence_grader.py#L143) và [query_frames.py:62](../ai_core/orchestration/ocop/query_frames.py#L62) nhận diện toàn bộ tập tên bằng giá trị ô chính xác trong nhóm provenance của bản ghi. Vẫn yêu cầu nguồn đúng, bằng chứng hợp lệ, không fallback và không có trạng thái chặn. Danh tính bản ghi chỉ chứng minh độ phủ truy xuất; không thay kiểm entailment của câu trả lời. [Kiểm phủ toàn câu tại dòng 195](../ai_core/orchestration/ocop/evidence_grader.py#L195) nhất quán với kiểm từng phần.
- [workflow.py:312](../ai_core/orchestration/ocop/workflow.py#L312) bỏ optional khi công cụ chính bị chặn hoặc lookup đã đủ; ghi `not_needed` trong trace. [Dòng 894](../ai_core/orchestration/ocop/workflow.py#L894) giữ mục chủ động không dùng khỏi cảnh báo thiếu phần phụ.
- [planner.py:23](../ai_core/orchestration/ocop/planner.py#L23) đếm dispatch thực tế; [recovery tại workflow.py:486](../ai_core/orchestration/ocop/workflow.py#L486) giới hạn số phần theo ngân sách còn lại và ghi `call_count`. Mục bộ nhớ và mục bỏ qua không tiêu lượt gọi.

Tiền lệ: [Adaptive-RAG](https://aclanthology.org/2024.naacl-long.389/) điều chỉnh số bước truy xuất theo độ phức tạp; [CRAG](https://arxiv.org/abs/2401.15884) dùng đánh giá chất lượng truy xuất để quyết định hành động kế tiếp. Ở đây dùng hợp đồng bản ghi và khung ngôn ngữ có sẵn để quyết định bảo thủ, không thêm mô hình phân loại.

Kiểm chứng hiện có: 15 test hồi quy offline đạt. Tắt riêng sửa grader: 4 test thất bại; tắt tối ưu thực thi: 2 thất bại; tắt sửa đếm ngân sách: 2 thất bại. Lỗi recovery nhiều phần, cảnh báo optional và tách hai tên thành hai yêu cầu đều đã có lượt test đỏ trước sửa, xanh sau sửa. Nhóm planner/recovery hiện đạt 31/31. Toàn bộ Python/OCR trên bản sửa hiện tại: 1.039 test đạt; lint đạt.

Gọi thẳng lookup và grader sau sửa: vẫn 14 đoạn, giữ nguyên điểm lexical 0,125/0; 14 đoạn được nhận theo nhóm định danh, `sufficient_for_generation`. Một lượt API trung gian còn tìm thừa ở tên đầy đủ kết hợp tên viết tắt: grader nhận đủ định danh nhưng bước tách tại chữ `và` báo thiếu phần sau. Đã đồng nhất kiểm phủ toàn câu với kiểm phủ từng phần; câu có vị từ bổ sung vẫn không đạt khung lookup đầy đủ.

| Bộ đo API riêng, LLM thật | Trước planner | Sau planner |
| --- | --- | --- |
| Đúng tập thực thể | 6/6 | 6/6 |
| Đúng intent / có lookup bắt buộc | 6/6 / 6/6 | 6/6 / 6/6 |
| Chỉ dùng lookup | 0/6 | 4/6 |
| Bốn ca cặp sản phẩm: số lần tìm bổ sung | 4 | 0 |
| Bốn ca cặp sản phẩm: median thời gian | 62,2 giây | 11,3 giây |

Bốn thời gian sau lần lượt 13,0 / 10,8 / 10,0 / 11,8 giây. Đây là phép đo của cùng bốn ca, không suy rộng thành bảo đảm độ trễ. Hai ca ba sản phẩm vẫn cần tìm bổ sung: phép gọi lookup trực tiếp chỉ trả 14 đoạn của hai sản phẩm. Grader mới giữ trạng thái chưa đủ, không nhận nhầm tập ba tên đã hoàn tất; chuyển việc kiểm adapter sang thành phần 4. Chưa kết luận chất lượng đáp án từ việc có citation; vai trò chủ thể và cửa sổ nguồn tiếp tục kiểm ở các tầng tương ứng.

| Bộ phát triển khóa, rerank + LLM stub | Trước planner | Sau planner |
| --- | --- | --- |
| `intent_ok` | 49/51 | 49/51 |
| `tool_ok` | 50/51 | 50/51 |
| `page_in_prompt` | 35/35 | 35/35 |
| `top1_page_ok` | 28/35 | 28/35 |
| `content_ok` / lỗi chạy | 35/35 / 0 | 35/35 / 0 |

Median/max bộ khóa trước 17,58/136,23 giây; sau 16,21/146,21 giây. Không quy biến động thời gian một lượt thành mức cải thiện chung.

Dấu vân tay và trạng thái sau sửa: `ocop-evidence-b531594eddc8`, ready, lineage_ok=true, neo4j_ready=true, 12.619 nút / 22.429 cạnh. Lượt đo API bị khởi động đồng thời với phép tắt sửa đã loại, không dùng chấm điểm. Bộ 26 câu chạy sau bộ riêng bị lỗi native `c10.dll` tại phép forward của reranker ở B2; lượt này không dùng tính tỉ lệ chất lượng. Bộ khóa đã chạy xong qua evaluator chính thức cùng trọng số/profile và biện pháp đọc tensor tạm đã nêu.

| Bộ 26 câu API, LLM thật | Trước planner | Sau planner |
| --- | --- | --- |
| Phản hồi HTTP 200 | 26/26 | 26/26 |
| Đúng tuyến | 26/26 | 26/26 |
| Đúng công cụ / trần riêng từng câu | 26/26 | 26/26 |
| Đáp án theo bộ chấm riêng | 25/26 | 25/26 |

Lượt API sau hợp lệ dùng cùng số luồng 6, khởi tạo trước khi nạp mô hình theo [hướng dẫn PyTorch](https://docs.pytorch.org/docs/stable/generated/torch.set_num_threads.html), cùng trọng số, hybrid, rerank 24. B2 chạy riêng một lần rồi toàn bộ 26 câu: 27/27 HTTP 200, không có native crash. Đây là phép thử vận hành, chưa chứng minh riêng việc khởi tạo luồng là nguyên nhân chữa lỗi. Kiểm trace với `call_count`: cao nhất ba lượt, không vượt năm hoặc trần riêng của từng câu. C3 tiếp tục hỏi văn bản chứa mẫu; không đổi gold hoặc chính sách làm rõ. Cách khởi động chuẩn và đọc tensor bền vững tiếp tục xử lý ở tầng truy xuất/cấu hình; mã vận hành tạm không đưa vào repo.

## 3–10. Chưa duyệt

Tiếp tục từ thành phần 3. Chưa có kết luận đạt cho các thành phần này.
