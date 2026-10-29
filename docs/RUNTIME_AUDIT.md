# Kiểm tra các tầng truy vấn OCOP — 28–29/10/2026

Bản tổng hợp kết quả debug runtime trên corpus hiện hành, hybrid + rerank.
Đây là số đo lịch sử, không phải phép đo mới của các lượt dọn repo. Gold và lock
không đổi; unit test chứng minh hợp đồng, không thay thế chất lượng trả lời API.
Lịch sử chi tiết của hai nhật ký gốc được giữ trong Git.

## Bất biến từng tầng

| Tầng | Bất biến |
| --- | --- |
| Router, hội thoại, catalog | Tên/tập thực thể được bảo toàn; đại từ chỉ trỏ đối tượng đã nhắc; lời chào giữ chủ đề; năm không thay quyết định đã ghim |
| Planner, workflow | Chỉ dispatch tool thuộc registry, tối đa năm lượt thực tế kể cả recovery; trạng thái chặn không mở tìm kiếm chung; optional không làm thiếu tool bắt buộc |
| Truy xuất | Giữ model/revision, chiều vector, corpus và bộ lọc nguồn; chỉ nạp trọng số cục bộ; khởi tạo CPU trước tensor work; tải/tính mô hình dùng khóa chung |
| Công cụ | Mã văn bản không giải được không mở phạm vi nguồn; bộ lọc và giới hạn đầu ra phải giữ danh tính từng bản ghi và phản ánh phần còn thiếu |
| Bằng chứng, ngữ cảnh | SOURCE lấy từ đoạn gốc; cửa sổ giữ mệnh đề/facet được hỏi; mọi nguồn chia sẻ ngân sách cứng; verifier đọc đúng cửa sổ mô hình thấy |
| Sinh, kiểm chứng | Quote nguyên văn không tự chứng minh nghĩa; số và phủ định phải khớp nguồn và chủ thể; câu hỏi không cấp quyền khẳng định số; cổng điểm/sao không được bỏ qua |

Hợp đồng API/frontend ở [ARCHITECTURE](ARCHITECTURE.md); tham số chạy ở
[CONFIGURATION](CONFIGURATION.md); cách đo và ý nghĩa chỉ số ở
[EVALUATION](EVALUATION.md). Các dự án tham khảo được tập trung tại
[ADR-010](adr/010-reference-projects-and-what-was-adopted.md).

## Tầng hỏng, nguyên nhân và cơ chế sửa

| Tầng hỏng | Nguyên nhân | Cách sửa |
| --- | --- | --- |
| `catalog.link` | Partial matching bỏ dấu; Unicode NFD và ranh giới danh sách bị xử lý sai; mã viết thường mất match | NFC, chính sách dấu thống nhất, ranh giới tên và hình dạng mã từ nhãn catalog |
| Router/slots | Nhánh exact loại partial và các tên còn lại | Hợp nhất match không chồng vị trí, khử trùng, giữ `product_names` theo thứ tự |
| Bộ nhớ | Mọi lượng từ lấy hai tên; giới hạn referent ngắn hơn slots | Lượng từ theo cấu hình, kiểm đủ số đối tượng, thống nhất giới hạn tên |
| Evidence grader | Overlap thấp ở ô định danh khiến lookup đủ vẫn tìm thêm; optional rỗng làm giảm độ phủ bắt buộc | Kiểm tập tên trong nhóm provenance và khung lookup đầy đủ; tách optional khỏi missing tools |
| Workflow/planner | Tool chính bị chặn vẫn chạy optional; đếm bộ nhớ/mục bỏ qua như dispatch; recovery nhiều phần vượt trần | Chặn optional đúng trạng thái, đếm dispatch thực tế và `call_count`, giới hạn phần theo ngân sách còn lại |
| Model runtime | Bộ đọc mmap fault; khởi tạo luồng muộn; cache không khóa constructor/tính toán | Bộ đọc theo cấu hình, CPU khởi tạo sớm, khóa tải/tính dùng chung; không quy native fault về một nguyên nhân duy nhất |
| Cache rerank | Thiếu ngân sách token trong key; cache hit mất chẩn đoán cắt đoạn | Key gồm ngân sách hiệu lực; giữ kiểm tokenizer và cờ truncation khi cache hit |
| `search_graph` | Mã văn bản không giải được thành `None` rồi chọn seed theo tên | Từ chối trước khi mở đồ thị; dùng source ID đã giải |
| `lookup_recognition` | Tính đủ trước lọc; cắt theo ô khiến bản ghi đầu chiếm ngân sách | Tính missing sau lọc/giới hạn; phân bổ luân phiên theo danh tính bản ghi |
| Lookup/open span | Cue và ngân sách sao chép trong mã; kết quả rỗng thiếu trạng thái | Đọc cấu hình ngôn ngữ/truy xuất; trả `ok`/`no_results` rõ ràng |
| `_evidence` | Mô tả quan hệ ghép trở thành quote | Chỉ đoạn gốc tạo citation; graph mô tả hướng dẫn chọn nguồn |
| `select_window` | Chấm toàn câu rồi cắt đầu; hòa điểm chọn dòng ngắn; độ phủ trước cắt khác prompt | Chấm cửa sổ thực sự vừa ngân sách theo vị trí từ và facet |
| `_most_relevant`/`fit_budget` | Nhánh terms rỗng bỏ facet; quota cộng ngoài giới hạn; ghép ô theo bảng; nhãn nguồn vượt ngân sách | Giữ facet/quan hệ trong trần chung, ghép theo bản ghi/hàng, bỏ nguồn cuối nếu vẫn không vừa |
| Fallback phiếu | Mất evidence của nút con và phần tiếp nối trước BM25/dense | Giữ phạm vi liên kết và thứ tự nguồn tới anchor phiếu kế tiếp; thiếu anchor không mở toàn văn bản |
| Grounding/anchor | Quote thật bỏ qua kiểm nghĩa; quote đổi dấu câu/ghép metadata được nhận | Quote literal tối thiểu 15 ký tự; schema đầy đủ required; diễn đạt lại qua verdict riêng với quote gốc |
| Số/phủ định/điểm sao | Miễn số từ câu hỏi; so tập số; chỉ kiểm phủ định một chiều; ghép giá trị khác chủ thể | So giá trị–nhãn đại lượng, năm sự kiện, mệnh đề và bản ghi đúng chủ thể; chặn trường hợp bất đồng |
| Xét nghĩa | Thiếu nhãn vị trí hoặc văn bản chứa đoạn; cắt cửa sổ mất khối quan hệ | `resolved_locator` từ công cụ, metadata văn bản riêng, giữ chỗ cho quan hệ; metadata không thay thân quote |

## Số đo cuối của từng bộ

Các hàng thuộc thời điểm và tập câu khác nhau; không gộp thành một tỉ lệ chung.

| Bộ đo | Kết quả cuối được ghi nhận |
| --- | --- |
| Router: API riêng 6 ca | Tập sản phẩm 6/6, intent 6/6, tool bắt buộc 6/6; chưa giảm tìm bổ sung ở bước router |
| Catalog/bộ nhớ | Roundtrip tên 93/93; hội thoại năm lượt giữ phạm vi 5/5 |
| Planner: API riêng 6 ca | Đúng tập tên/intent/tool 6/6; chỉ lookup 4/6; bốn ca cặp sản phẩm giảm tìm bổ sung 4 → 0, median 62,2 → 11,3 giây |
| Truy xuất: bộ khóa | 59 lần search, 0 fallback, 0 lỗi; tối đa 24 ứng viên rerank; 24 lần có cờ cắt đầu vào |
| Truy xuất: API chuẩn | Hai cold-start, 30 request HTTP 200, không native crash; tối đa ba lượt tool |
| Công cụ: probe trực tiếp | 12/17 khi tắt sửa → 17/17; 13/13 test mới thất bại khi tắt sửa |
| API 26 câu sau phần công cụ | Tuyến 26/26, tool 26/26, không vượt ngân sách; rubric trả lời 24/26 |
| Ngữ cảnh: replay cùng đầu vào API | Đúng nguồn/trang 12/12 ở cả hai; đủ dữ kiện SOURCE 11/12 → 12/12; mô tả quan hệ ghép 2 → 0; hai ca phiếu 16 → 12 khối |
| API riêng sau phần ngữ cảnh: 16 ca, 18 request | Luồng 16/16, tool bắt buộc 16/16, intent chính theo gold hẹp 11/16, rubric trả lời 14/16; tối đa ba lượt tool |
| API riêng sau phần kiểm chứng: cùng 16 ca | Rubric trả lời 15/16; median 44,5 giây (phần ngữ cảnh 36,9 giây) |
| Test cuối đợt debug | Python/OCR 1.125 pass; frontend 15/15, build đạt |

| Bộ phát triển khóa, rerank + stub | Trước phần ngữ cảnh | Sau phần ngữ cảnh |
| --- | --- | --- |
| Lỗi truy vấn | 0/51 | 0/51 |
| Intent | 49/51 | 49/51 |
| Công cụ | 50/51 | 50/51 |
| Trang đúng trong prompt / đủ nội dung | 35/35 | 35/35 |
| Trang đúng xếp đầu | 28/35 | 30/35 |
| Trung vị / lớn nhất (giây) | 17,56 / 128,16 | 17,12 / 123,52 |

Không kết luận tăng tốc từ các lượt có trạng thái nạp mô hình/cache khác nhau.
Phần kiểm chứng không đổi router/planner và không chạy lại bộ chọn luồng.
Đối chứng offline kiểm chứng: 11 ca sai bị chặn, 4 ca đúng giữ nguyên; cả 11 ca
sai thất bại với hàm cũ. Đối chứng ngữ cảnh: 14/14 ca thất bại với hàm cũ, cùng
2/2 ca fallback; ca tiếp nối phiếu có lượt đỏ khi tắt riêng helper.

Vân tay `ocop-evidence-b531594eddc8`; `state=ready`, `lineage_ok=true`,
`neo4j_ready=true`; 12.619 nút / 22.429 cạnh giữ nguyên.

## Giới hạn đã biết

- Stub đo nội dung prompt; citation đúng không chứng minh câu trả lời đúng.
- Bộ khóa còn lệch intent ở ID 12/36 và tool ở ID 35; giữ gold và hành vi từ chối.
- API sau ngữ cảnh có truy xuất bổ sung: tool bắt buộc đạt không chứng minh hết
  truy xuất thừa. Intent chính 11/16 không được thay bằng chỉ số luồng 16/16.
- Hai ca ba sản phẩm ở bộ planner vẫn cần tìm bổ sung vì lookup chỉ trả hai tên.
- C3 hỏi rõ văn bản chứa mẫu. B3/B5 có biến thiên sinh/kiểm chứng dù cùng bằng chứng;
  ca cuối `sheet-environment` có verdict `entails=false` dù từng đạt ở lượt trước.
- Tăng độ trễ do lượt xét nghĩa; kết quả 15/16 không phải bảo đảm cho lần chạy sau.
- `/criteria` và `/products` trả rỗng; không tạo bản ghi thay thế trong lượt debug.
- Đợt này chưa đo lại mã lỗi 422/404/503 và `/graph/subgraph` ở thành phần 7–10.
