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

## 5–10. Chưa kết luận

Tiếp tục theo thứ tự sau khi hoàn tất phép đo thành phần 4; không dùng kết quả
test thành phần 4 để tuyên bố các thành phần sau đã hoàn tất.
