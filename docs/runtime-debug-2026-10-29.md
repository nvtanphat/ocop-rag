# Kiểm tra các tầng truy vấn OCOP GraphRAG — 2026-10-29

Phạm vi tiếp nối: thành phần 4–10. Không thay nguồn, OCR, extraction, knowledge,
graph, chunker hoặc chỉ mục. Các thay đổi chưa commit lúc tiếp quản được giữ nguyên.
Không sửa bộ câu hỏi phát triển hoặc lock. Kết quả chưa đo được ghi rõ là đang chờ.

Artifact đo cục bộ: `%TEMP%/ocop-runtime-audit-20261029/` (ngoài repository).
Các số chất lượng sinh phải lấy từ API với LLM thật; pytest và capture client chỉ
chứng minh hợp đồng hoặc nội dung prompt.

## 4. Công cụ

Bất biến:

1. Chỉ gọi công cụ thuộc registry của server.
2. Mã văn bản không giải được không trở thành truy vấn không giới hạn nguồn.
3. Lọc sao/vùng xét bản ghi công nhận, không ghép ô của các bản ghi khác nhau.
4. Độ đầy đủ của tập thực thể phản ánh kết quả thực sự trả về sau mọi bộ lọc.
5. Ngân sách kết quả giữ đại diện của các bản ghi trước khi lấy thêm ô cùng bản ghi.

| Ca | Tầng hỏng | Trước sửa | Nguyên nhân |
| --- | --- | --- | --- |
| graph-bad-document | `search_graph` | 33 kết quả từ nguồn khác, `checked_source_graph` | Mã không giải được thành `None`, rồi chọn seed theo tên sản phẩm |
| named-set-stars | `lookup_recognition` | Còn 1/2 sản phẩm nhưng `status=ok` | Tính độ đầy đủ trước bộ lọc sao |
| named-set-event-year | `lookup_recognition` | Còn 1/2 sản phẩm nhưng `status=ok` | Tính độ đầy đủ trước bộ lọc năm sự kiện |
| producer-list / producer-stars | `lookup_recognition` | ST25 mất khỏi 15 ô trả về dù bản ghi có trong tập trước khi cắt | Cắt theo thứ tự ô, các bản ghi đầu chiếm hết ngân sách |
| open-missing / open-unknown | `open_source_span` | Không có `status` khi kết quả rỗng | Adapter chỉ trả mảng rỗng |
| configured-cues (3 ca) | Tìm văn bản / đồ thị | 0/3 cue giả trong cấu hình được áp dụng | Công cụ giữ bản sao cue trong mã |
| configured-budget/noun/expansion (3 ca) | Lookup | 0/3 cấu hình giả được áp dụng | Ngân sách, danh từ sao và từ mở rộng tìm kiếm viết trong mã |

Sửa trong `ai_core/orchestration/ocop/tools.py` (điểm chính: dòng 36, 116, 489,
714, 741, 1028 và nhánh `search_graph`):

- Từ chối mã văn bản không giải được trước khi mở đồ thị; tái sử dụng source ID đã giải.
- Tính `missing_entities` sau lọc vùng/sao/năm và giới hạn đầu ra.
- Khi vượt ngân sách, lấy luân phiên theo `(source_id, graph_node_ids)`; không đổi
  nội dung, thứ tự ô trong từng bản ghi hoặc tăng giới hạn 15 ô.
- `open_source_span` trả `ok`/`no_results` rõ ràng.
- Dùng cue hạn nộp, văn bản địa phương, quan hệ và danh từ sao từ cấu hình ngôn ngữ;
  thêm `cues.evidence_search_terms` với giá trị mặc định giữ nguyên từ mở rộng cũ.
- Ngân sách lookup lấy từ `agent.lookup_max_rows` (mặc định vẫn 15).

Cơ chế dùng danh tính và metadata nguồn, không chứa tên sản phẩm hoặc mã văn bản.
Tiền lệ: [Haystack metadata filtering](https://docs.haystack.deepset.ai/docs/retriever)
giới hạn tập đầu vào theo điều kiện;
[MetaFieldGroupingRanker](https://docs.haystack.deepset.ai/docs/3.1/metafieldgroupingranker)
tổ chức bằng chứng theo nhóm metadata trước khi đưa cho LLM. Việc chia lượt trong
ngân sách ở đây là lựa chọn tất định của dự án, không phải mã sao chép từ Haystack.

Kiểm chứng đã chạy:

- `test_tool_record_scope.py`: 35 test; 13 ca mới đã được chạy đỏ trước khi sửa.
- Đối chứng âm: tắt các sửa trong bộ nhớ bằng plugin pytest tạm; cả 13 test mới fail.
  Không thay file workspace trong phép đối chứng.
- Bộ test liên quan công cụ/đồ thị/phạm vi/no-corpus-literals: 59/59 pass.
- Probe trực tiếp 17 ca trên kho thật: 12/17 khi tắt sửa, 17/17 sau sửa. Probe lấy canonical
  organization slot từ router/catalog trước khi gọi công cụ; không tự đặt nhãn rút gọn.
- Gold của hai ca danh sách được đối chiếu trực tiếp PDF `VN.HAIPHONG.QD525.2026`,
  trang 3: ST25 và HANA nằm trong cùng nhóm chủ thể; không dùng output công cụ làm gold.
- Vân tay `ocop-evidence-b531594eddc8`; `state=ready`, `lineage_ok=true`,
  `neo4j_ready=true`; số nút/cạnh `human_verified`: 12.619 / 22.429.

Toàn bộ pytest sau sửa cơ chế: **1.081 passed**. Sau khi nối cấu hình:
**1.087 passed**, 3 cảnh báo thư viện, không có lỗi. Pytest chạy với môi trường
fixture mặc định; chỉ đặt hybrid + rerank khi chạy benchmark/API thật.

| Bộ phát triển cố định, rerank + stub | Trước sửa | Sau sửa |
| --- | --- | --- |
| Lỗi truy vấn | 0/51 | 0/51 |
| `intent_ok` | 49/51 | 49/51 |
| `tool_ok` | 50/51 | 50/51 |
| `page_in_prompt` | 35/35 | 35/35 |
| `top1_page_ok` | 28/35 | 28/35 |
| Trung vị / lớn nhất | 17,19 / 122,72 giây | 17,56 / 128,16 giây |

Không có hồi quy ở bốn chỉ số nghiệm thu. Không kết luận cải thiện độ trễ từ hai lượt này.
API thật ở bản sửa trước bước nối cấu hình: 26/26 tuyến, 26/26 công cụ, 0 câu vượt
ngân sách công cụ, 25/26 rubric câu trả lời. C3 trả `clarify` vì thiếu phiên bản
mẫu; đây là lựa chọn hành vi giữ nguyên, không đổi gold để tính thành pass.
Sau bước nối cấu hình: bộ phát triển cố định vẫn đạt đủ bốn chỉ số trong bảng;
pytest 1.087 pass; probe trực tiếp vẫn 17/17. API đã khởi động lại và chạy đủ
26 câu trên mã cuối: 26/26 tuyến, 26/26 công cụ, không vượt ngân sách, 24/26 rubric
trả lời. B3 có cùng danh sách citation/chunk nhưng `accepted=1` thành `accepted=0`,
`reasons=[no_claims]`; giữ như biến thiên LLM theo yêu cầu. C3 giữ hành vi hỏi rõ
phiên bản mẫu. Không đổi gold hoặc điều chỉnh mã để đuổi theo hai ca này.

Các điểm rubric về nội dung ở đây không thay thế phép kiểm quote nguyên văn của
thành phần 5 hoặc phép kiểm entailment của thành phần 6. Đã lưu riêng ca C2 có
anchor quote từ biểu diễn quan hệ đồ thị để kiểm ở thành phần 5.

## 5. Chọn bằng chứng và ngữ cảnh — đã nghiệm thu

Bất biến: SOURCE dùng đoạn gốc; giữ facet được hỏi dù không có từ nội dung;
cửa sổ phải còn mệnh đề liên quan sau cắt; tổng khối nguồn/token không vượt ngân
sách; bộ kiểm chứng đọc đúng cửa sổ mô hình nhìn thấy.

| Ca | Tầng hỏng | Trước sửa | Nguyên nhân |
| --- | --- | --- | --- |
| C2 API | `_evidence` | 2 anchor quote chứa `[REPLACES]` do công cụ ghép | Đưa mô tả quan hệ vào cùng luồng đoạn nguồn gốc |
| long-unbroken (2 ca) | `select_window` | Mất cả ALPHA/BETA dù chúng nằm trong đoạn được chọn | Chấm toàn câu dài, sau đó cắt đầu |
| feasible-coverage | `select_window` | Chọn đoạn có 3 từ ở xa nhau, cửa sổ thật chỉ còn 1; bỏ đoạn đủ 2 từ | Chấm độ phủ trước khi giới hạn cửa sổ |
| locator-only | `select_window` | Chỉ trả dòng `x` | Mọi điểm bằng 0, ưu tiên dòng ngắn nhất |
| code-facet | `_most_relevant` | Mất bằng chứng 1.6 khi `terms=[]` | Nhánh trả sớm bỏ qua facet |
| relation/siblings (3 ca) | `_most_relevant` | Vượt giới hạn 2 khối; lấy ô của bản ghi khác cùng bảng | Cộng quota ngoài giới hạn; chỉ dùng ID bảng để ghép ô |
| header-budget | `fit_budget` | Giữ nguồn dù riêng nhãn đã vượt ngân sách | Dừng thu hẹp ở kích thước tối thiểu nhưng không bỏ nguồn cuối |

Sửa ở `answer.py:141` (`_most_relevant`), `answer.py:261` (`_evidence`),
`context.py:65` (`_word_window`), `context.py:101` (`select_window`) và
`context.py:225` (`fit_budget`); thêm `context.max_table_siblings` vào cấu hình.
Mô tả `graph:` vẫn hướng dẫn chọn cửa sổ; chỉ các đoạn `graph-evidence:`/đoạn nguồn
gốc tạo citation. Câu quá dài được xét bằng lát cắt theo vị trí từ, chấm trên phần
thực sự vừa ngân sách, giữ ngữ cảnh quanh từ khớp. Facet/quan hệ và ô cùng bản ghi
chia sẻ giới hạn cứng; nhận diện ô cùng bản ghi bằng graph node ID hoặc hàng bảng,
không chỉ dựa vào ID bảng. Không đổi chunker hoặc dựng lại chỉ mục.

Tiền lệ: [LlamaIndex metadata replacement và sentence windows](https://developers.llamaindex.ai/python/examples/node_postprocessor/metadatareplacementdemo/)
tách nội dung dùng truy xuất và ngữ cảnh cho mô hình;
[Lucene UnifiedHighlighter](https://lucene.apache.org/core/9_8_0/highlighter/org/apache/lucene/search/uhighlight/UnifiedHighlighter.html)
chấm passage theo vị trí từ khớp trong văn bản gốc. Chỉ áp dụng ý tưởng ở runtime,
không đổi bộ tách hoặc thêm thư viện.

Kiểm chứng: 63 test liên quan pass; 11 test mới đã chạy đỏ trước sửa và đều fail
khi phục hồi hàm trước sửa trong bộ nhớ. Toàn bộ pytest: **1.098 pass**, 3 cảnh báo.
Vân tay và trạng thái bất biến giữ nguyên. Đang chạy bộ phát triển cố định và chờ
đo lại API thật; chưa kết luận nghiệm thu thành phần 5.

Probe trực tiếp `search_graph` → `_evidence` trên câu C2 và cùng kết quả công cụ:
trước có 3 khối SOURCE, trong đó 2 khối mô tả quan hệ ghép; sau còn 1 khối gốc,
0 khối ghép. Đoạn gốc vẫn giữ đủ 148, 1489, “60 ngày”, trang 13. Probe không gọi
mô hình và không sửa nguồn, graph hoặc chỉ mục.

Lượt đo đầu sau sửa chưa đạt: `page_in_prompt` và `content_ok` giảm từ 35/35 xuống
34/35; không chấp nhận lượt này. Ca 15 hỏi nguồn gốc sản phẩm ở phiếu 1: trong
36 ứng viên, trang 18 mất ngay khi chọn 12 khối, trước bước ngân sách (0 khối bị
bỏ vì ngân sách). Hai cơ chế phối hợp gây lỗi: fallback của `lookup_criterion`
làm mất tập evidence thuộc phiếu; nội dung trang cha không hiển thị lại đóng góp
điểm liên quan cho đoạn con khác. Không thay gold hoặc nguồn.

Bổ sung tại `tools.py:794` và `tools.py:959`: fallback giữ tập evidence của các nút con thuộc phiếu, truyền cờ rerank,
và từ chối mở rộng khi phạm vi rỗng. Bộ chọn chấm raw text cùng tiêu đề cha thực
sự hiển thị; facet ưu tiên dòng tiêu đề khớp nội dung hỏi. Capture lại pipeline
thật giữ 12 khối thuộc các trang 18/20/21/22, thay cho các phiếu khác. Cần cả sửa
phạm vi lẫn chọn đoạn; không quy toàn bộ kết quả cho riêng bộ chọn.

Hai test phạm vi và ba test ngữ cảnh bổ sung đều đã đỏ trước sửa. Đối chứng âm:
14/14 test ngữ cảnh fail khi nạp hàm cũ trong bộ nhớ; 2/2 test fallback fail với
module tại commit `19fbfe1`. Bộ liên quan 98 pass; toàn bộ **1.103 pass**. Vân tay,
ready/lineage/Neo4j và 12.619/22.429 giữ nguyên. Lượt benchmark đầy đủ đầu bị dừng
trong thư viện mô hình (`deallocated bytearray object has exported buffers`),
không có báo cáo hoàn chỉnh; đang chạy lại với API tắt và duy nhất một tiến trình
nạp mô hình. Chưa dùng capture một ca để kết luận cả bộ đo đã đạt.

### Tiếp quản và tái lập phép đo

Thư mục artifact cũ không còn khi tiếp quản. Đã tạo lại bộ probe trong
`%TEMP%/ocop-runtime-audit-20261029/`, đọc gold trực tiếp từ EvidenceUnit và PDF
trước khi gọi API; không sửa bộ phát triển hoặc lock. Giữ nguyên các thay đổi
workspace và lưu bản sao bytes ban đầu ngoài repository.

- Chạy lại toàn bộ: **1.103 pass**, 3 cảnh báo thư viện; bộ liên quan: **101 pass**.
- Chạy lại đối chứng bằng hàm tại `19fbfe1` trong bộ nhớ: **14/14** ca ngữ cảnh
  và **2/2** ca fallback theo phiếu thất bại đúng assertion. File workspace
  không bị phục hồi trong phép đo. Log: `component5-negative.txt`.
- Probe `replaces-expiry` gọi trực tiếp `search_graph` với cùng 8 dòng kết quả:
  trước: 3 SOURCE, 2 mô tả quan hệ ghép, không còn “60 ngày”; sau: 1 SOURCE gốc,
  0 mô tả ghép, có “60 ngày”, vẫn trang 13. Artifact: `component5-graph-probe.json`.
- Lời gọi structured output thật với schema claims thành công, đủ trường bắt buộc.
- Vân tay vẫn `ocop-evidence-b531594eddc8`; ready/lineage/Neo4j đều đạt;
  12.619 nút và 22.429 cạnh không đổi.

Lượt đo rerank + stub đầy đủ đang chạy với API tắt. Chưa nghiệm thu thành phần 5
cho tới khi có đủ benchmark có khóa và API thật trên mã cuối.

Lượt chạy lại sau tiếp quản hoàn tất 51 câu: 0 lỗi, intent 49/51, tool 50/51,
page/content 34/35, top1 29/35, trung vị 17,58 giây, lớn nhất 124,60 giây.
Artifact: `component5-dev-at-resume.json`. **Không nghiệm thu** vì ca 16 mất trang.
Capture riêng lặp lại lỗi 0/1 ở ca 16. Đo trực tiếp fallback cho thấy phạm vi chỉ
4 EvidenceUnit, không chứa phần tiếp nối mang tiêu đề 1.6 ở trang 18; đoạn này
bị loại trước BM25/dense, không phải do cửa sổ hoặc ngân sách prompt.

Sửa bổ sung `_section_evidence_units` trong `tools.py`: giữ các đơn vị cùng nguồn
từ anchor của phiếu đến trước anchor phiếu tiếp theo, theo `source_order` có sẵn.
Không lấy khối nguyên trang. Nếu không có phiếu kế tiếp, dừng ở đơn vị cuối đã
liên kết; thiếu anchor thì giữ phạm vi cũ, không mở toàn văn bản. Phạm vi ca 16
từ 4 thành 7 đơn vị và chứa đúng phần tiếp nối. Không sửa graph hoặc chỉ mục.
Tiền lệ: [LlamaIndex Recursive Retriever + Node References](https://developers.llamaindex.ai/python/framework/integrations/retrievers/recursive_retriever_nodes/)
đi từ nút liên kết tới nội dung nguồn; ranh giới theo thứ tự nguồn là cơ chế
tất định riêng của dự án.

Test `test_criterion_fallback_keeps_section_continuations_before_the_next_sheet`
đỏ trước sửa, xanh sau sửa, đỏ khi tắt riêng helper trong bộ nhớ; đồng thời
kiểm loại nguồn khác, phiếu kế tiếp và khối nguyên trang. Bộ liên quan 41 pass;
toàn bộ **1.104 pass**. Lock bộ phát triển khớp SHA-256; các bất biến giữ nguyên.
Đang đo lại ca 15–16 và bộ đầy đủ trước khi mở API.

Kết quả cuối: ca 15–16 đều 2/2 page/content/top1; sau đó cùng hàm benchmark
`evaluate_question_sets.evaluate`, đủ 51 câu và đầy đủ lịch sử hội thoại, có
checkpoint sau mỗi câu, đạt bảng dưới. Lock được kiểm trước/sau; không đổi gold.

| Bộ phát triển, rerank + stub | Mốc trước phần 5 | Khi tiếp quản | Sau sửa cuối |
| --- | --- | --- | --- |
| Lỗi truy vấn | 0/51 | 0/51 | 0/51 |
| Intent | 49/51 | 49/51 | 49/51 |
| Công cụ | 50/51 | 50/51 | 50/51 |
| Trang đúng trong prompt / đủ nội dung | 35/35 | 34/35 | 35/35 |
| Trang đúng xếp đầu | 28/35 | 29/35 | 30/35 |
| Trung vị / lớn nhất (giây) | 17,56 / 128,16 | 17,58 / 124,60 | 17,12 / 123,52 |

Artifact: `component5-dev-after-section-scope.json`. Không kết luận tăng tốc từ
những lượt chạy này vì trạng thái nạp mô hình/cache khác nhau.

API thật sau khởi động lại: health ready, hybrid + rerank, Neo4j heap 1 GB.
Bộ riêng 16 ca (18 request, gồm hội thoại ba lượt), gold khóa ngoài repository:
16/16 luồng hợp lệ, 16/16 công cụ bắt buộc, không gọi tool lạ, tối đa 3 lượt gọi.
Nhãn ý định chính khớp tập gold hẹp 11/16; giữ nguyên số này, không sửa gold:
các ca phối hợp mang ý định chính procedure/temporal, và lượt nối tiếp mang
FOLLOWUP, vẫn giữ capability và luồng tương ứng. Có truy xuất bổ sung trong trace;
không dùng chỉ số công cụ bắt buộc để tuyên bố không truy xuất thừa.

Replay bộ chọn cũ/mới trên cùng đầu vào công cụ API: đúng nguồn/trang 12/12 ở cả
hai; đủ dữ kiện trong SOURCE 11/12 → 12/12; SOURCE mô tả quan hệ ghép 2 → 0;
hai ca phiếu từ 16 → 12 khối mà vẫn giữ dữ kiện. Không phải phép so sánh chất
lượng sinh trước/sau. Artifact: `component5-context-comparison.json`.

Rubric câu trả lời có trích dẫn: 14/16. Ca renewal có đúng 180/120 ngày trong
prompt nhưng claim bị loại `grounding_terms_missing`; ca injection chỉ báo phần
không được cung cấp, bỏ câu hỏi hiệu lực hợp lệ. Chuyển hai ca này sang thành
phần 6, không quy lỗi cho chọn bằng chứng. Đã sửa phép chấm tạm để đếm bước tool
và `recovery.call_count`, không đếm tất cả dòng trace; nội dung được chấm độc lập
với status `partial_evidence`. Không thay câu hỏi hoặc gold.

Toàn bộ 1.104 test pass; vân tay, ready/lineage/Neo4j và 12.619/22.429 giữ nguyên.
Thành phần 5 được nghiệm thu trên mã này; chưa kết luận thành phần 6–10.

## 6–10. Chưa kết luận

Tiếp tục theo thứ tự; không dùng kết quả các thành phần trước để tuyên bố các
thành phần sau đã hoàn tất.
